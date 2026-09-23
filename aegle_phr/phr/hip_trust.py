"""
Which bridges may push health data directly to us.

THE PROBLEM. A HIP's section 7 data push is sent STRAIGHT to the
dataPushUrl we supplied -- it is not relayed by the ABDM gateway. So its
bearer token is the HIP's OWN gateway token, carrying azp = the HIP's
bridge (client) id, not "gateway" and not ours. abdm_core's callback
verification accepts a fixed set of azp values, so every genuine push
from a HIP we had not hard-coded was rejected 401. Confirmed live
2026-09-23: four transfers, all correctly signed, all refused.

WHY A STATIC ALLOWLIST CANNOT FIX IT. A Health Locker receives pushes
from whichever hospitals its patients happen to have visited. Their
bridge ids are not knowable when the locker is configured, and there may
be thousands. Listing them in .env works for exactly one sandbox and
fails for every real deployment.

WHY NOT JUST SKIP THE azp CHECK ON THAT ROUTE. That was the first
instinct, and it is weaker than what is done here. It would accept a
push from ANY ABDM-registered participant, including ones we have never
interacted with, leaning entirely on transaction correlation downstream.

WHAT THIS DOES INSTEAD -- narrower than either option. At the moment we
ask a HIP for data, we look that HIP's bridge id up in ABDM's own
registry (GET /bridge-service/serviceId/<facility>, which resolves
facilities on OTHER bridges -- verified live) and trust exactly that one
value. So the set of bridges allowed to push to us is, at any moment,
precisely the set we have outstanding data requests with. A bridge we
have never sent a request to still cannot push to us at all, which a
blanket relaxation would have permitted.

Nothing here weakens verification: signature, iss and exp are still
checked against ABDM's live JWKS by abdm_core exactly as before, and
this only ever ADDS a specific, registry-confirmed value to the azp set.
Authorization for a push still additionally requires a transactionId we
issued and care contexts inside our own stored consent artefact -- see
callbacks/hiu_services.handle_health_information_push().
"""

from typing import Any

import requests

from abdm_core.config import GatewayConfig, configure, get_config
from abdm_core.http import generate_request_id, generate_timestamp
from abdm_core.observability.flow_logger import log_error, log_phase
from abdm_core.session import get_gateway_token

from aegle_phr.settings import Settings

_TIMEOUT_SECONDS = 30

# facility id -> bridge id, resolved once per process. ABDM's registry is
# not going to reassign a facility to a different bridge mid-transfer,
# and the lookup is a live network call we should not repeat per push.
_bridge_id_cache: dict[str, str] = {}


def resolve_bridge_id(settings: Settings, facility_id: str) -> str | None:
    """
    The bridge (client) id that owns a facility, per ABDM's registry.

    Returns None rather than raising: failing to resolve must degrade to
    "this push will be rejected", never to "the data request cannot be
    made at all". A 401 on a push is recoverable by retrying the request
    later; refusing to ask for data is not.
    """
    if not facility_id:
        return None
    if facility_id in _bridge_id_cache:
        return _bridge_id_cache[facility_id]

    url = f"{settings.abdm_gateway_base_url.rstrip('/')}/bridge-service/serviceId/{facility_id}"
    headers = {
        "Content-Type": "application/json",
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "X-CM-ID": settings.abdm_x_cm_id,
        "Authorization": f"Bearer {get_gateway_token()}",
    }

    try:
        response = requests.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        log_error(f"Could not look up the bridge for facility {facility_id}: {exc}")
        return None

    if response.status_code != 200:
        log_error(f"Bridge lookup for facility {facility_id} returned {response.status_code}")
        return None

    try:
        record = response.json()
    except ValueError:
        log_error(f"Bridge lookup for facility {facility_id} returned a non-JSON body")
        return None

    if isinstance(record, dict) and "bridgeId" not in record:
        for key in ("service", "data", "bridgeService"):
            if isinstance(record.get(key), dict):
                record = record[key]
                break

    bridge_id = record.get("bridgeId") if isinstance(record, dict) else None
    if not bridge_id:
        log_error(f"Bridge lookup for facility {facility_id} carried no bridgeId")
        return None

    _bridge_id_cache[facility_id] = bridge_id
    return bridge_id


def trust_bridge(bridge_id: str | None) -> bool:
    """
    Adds one bridge id to the azp values accepted on inbound callbacks.

    Rebuilds GatewayConfig because extra_allowed_azp is a frozenset on a
    frozen dataclass -- deliberately immutable, so this goes through
    configure() rather than mutating shared state in place.
    Idempotent: re-trusting an already-trusted bridge is a no-op.
    """
    if not bridge_id:
        return False

    config = get_config()
    if bridge_id in (config.extra_allowed_azp or frozenset()):
        return False

    configure(GatewayConfig(
        client_id=config.client_id,
        client_secret=config.client_secret,
        gateway_base_url=config.gateway_base_url,
        x_cm_id=config.x_cm_id,
        extra_allowed_azp=frozenset(config.extra_allowed_azp or ()) | {bridge_id},
    ))
    log_phase(f"Now accepting direct data pushes signed by bridge {bridge_id}")
    return True


def trust_bridge_for_facility(settings: Settings, facility_id: str) -> str | None:
    """
    Resolve-and-trust, called at the moment we ask a HIP for data.

    That timing is the whole point: trust is granted because WE decided
    to request data from this hospital, not because someone showed up
    claiming to be it.
    """
    bridge_id = resolve_bridge_id(settings, facility_id)
    trust_bridge(bridge_id)
    return bridge_id


def warm_trusted_bridges(bridge_ids: Any) -> int:
    """
    Re-trusts bridges from already-recorded state, with NO network calls.

    Needed because the trust set lives in process memory: a restart while
    a transfer is in flight would otherwise 401 the HIP's push for a
    request we genuinely made moments earlier. Called at startup with the
    bridge ids stored on outstanding data requests.
    """
    count = 0
    for bridge_id in bridge_ids or ():
        if trust_bridge(bridge_id):
            count += 1
    return count
