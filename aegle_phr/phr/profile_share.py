"""
Scan & Share (spec section 5), PATIENT side -- P22. The other end of the
handshake repo/'s P21 built: the patient's app scans a facility's counter
QR, shares the profile through the CM, and gets back a queue token.

This module owns the two outbound calls:

    share_profile()     POST {hiecm}/patient-share/v3/share
    get_token_details() GET  {hiecm}/patient-share/v3/profile/getTokenDetails

HEADERS -- THE SAME FAMILY AS uil.py, NOT THE PROFILE FAMILY. Authorization
(gateway) + X-AUTH-TOKEN (the LITERAL header name, value RAW with NO
"Bearer " prefix) + X-CM-ID + X-HIU-ID + REQUEST-ID/TIMESTAMP. The raw,
unprefixed X-AUTH-TOKEN is not a guess: uil.py does it that way and has
been live-proven doing it. repo/server/linking.py's commented-out discover
prefixes it with "Bearer", but that code has never once executed -- follow
the one that has.

X-HIU-ID = settings.abdm_hiu_id, THE PHR FACILITY ID (IN3310002290), not
the client/bridge id. Settled live 2026-09-23 against UIL discover: the
bridge id returns 400 "Invalid HIU ID"; the facility id returns 202. Same
header family, same value.

X-HIU-ID IS DELIBERATELY ABSENT FROM get_token_details(). It is not in our
Postman collection's saved request for that call, and this module does not
add headers ABDM has not been observed to want.

=============================================================================
WHAT IS UNCONFIRMED HERE, AND WHY
=============================================================================
UNCONFIRMED: share_profile()'s RESPONSE SHAPE. Our Postman collection has
zero saved responses on this call, and NHA's reference wrapper implements
only the HIP side of this flow, so there is no reference implementation of
the patient side to read either. Every comparable patient-authenticated
call in this project returns a bare 202 with nothing useful in the body
(see uil.discover()'s own docstring), so that is the assumption -- but
nothing here PARSES the response. The body is returned verbatim and stored
verbatim, and `ok` comes from the status code alone.

UNCONFIRMED: get_token_details()'s RESPONSE SHAPE. Same silence, same
handling -- returned verbatim, parsed nowhere in this module.

UNCONFIRMED: whether metaData.hprId / latitude / longitude may be OMITTED
or must be present-but-null. They describe the FACILITY's practitioner and
physical location, which a patient app has no way to know. Both Postman
samples send them populated because both were captured from the facility's
own side of the exchange. This module omits the keys entirely; if ABDM
400s asking for them, send explicit nulls instead and record which worked
right here.

Same per-module _headers()/_parse()/_execute() shape as uil.py,
subscription.py and consent.py -- duplicated, not imported, per this
project's own established convention (see subscription.py's own banner).
"""

import time
from typing import Any

import requests

from abdm_core.http import call_with_retry, generate_request_id, generate_timestamp
from abdm_core.observability.flow_logger import log_api_call, log_error, log_phase
from abdm_core.session import get_gateway_token

from aegle_phr.phr.call_log import archive
from aegle_phr.phr.enrollment import AbdmResult
from aegle_phr.settings import Settings

_TIMEOUT_SECONDS = 30


def _headers(
    x_auth_token: str,
    x_cm_id: str,
    hiu_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, str]:
    """
    The Scan & Share outbound header shape.

    `hiu_id` is OPTIONAL here, unlike uil.py's own _headers() where it is
    required: the share call sends X-HIU-ID and getTokenDetails does not
    (see this module's banner). Passing None omits the header rather than
    sending an empty one.

    `request_id`: caller-supplied so the route can save the pending
    ProfileShareRequest row BEFORE the call completes -- the callback can
    genuinely arrive before our own HTTP response does. Same reason
    uil.py's own _headers() takes one.
    """
    headers = {
        "Content-Type": "application/json",
        "REQUEST-ID": request_id or generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-AUTH-TOKEN": x_auth_token,
        "X-CM-ID": x_cm_id,
    }
    if hiu_id:
        headers["X-HIU-ID"] = hiu_id
    return headers


def _parse(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _execute(
    route: str,
    method: str,
    url: str,
    headers: dict[str, str],
    payload: Any,
    description: str,
    params: dict[str, Any] | None = None,
    plaintext_secrets: tuple[str, ...] = (),
) -> AbdmResult:
    """
    GET and POST -- this module needs both, unlike uil.py's POST-only
    version. The GET branch is copied from subscription.py's own
    _execute(), which already had exactly this shape for its lookups.

    Never calls raise_for_status(): a 4xx from ABDM is an expected,
    handled outcome here (the whole response shape is unconfirmed), not an
    exception.
    """
    started = time.monotonic()

    def attempt() -> requests.Response:
        if method == "GET":
            return requests.get(url, headers=headers, params=params, timeout=_TIMEOUT_SECONDS)
        return requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT_SECONDS)

    archived_request = payload if payload is not None else (params or {})

    try:
        response = call_with_retry(attempt, description=description)
    except requests.exceptions.RequestException as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"{description} failed: {exc}")
        archive(route, url, archived_request, None, None, duration_ms, str(exc), plaintext_secrets)
        return AbdmResult(status_code=None, body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    body = _parse(response)

    log_api_call(description, url, response.status_code)
    archive(route, url, archived_request, response.status_code, body, duration_ms, None, plaintext_secrets)

    return AbdmResult(status_code=response.status_code, body=body)


def _clean_patient(patient: dict[str, Any]) -> dict[str, Any]:
    """
    Normalises the patient object the frontend supplies into the exact
    shape P21's parser expects.

    THE FRONTEND SUPPLIES THIS, NOT A SERVER-SIDE PROFILE FETCH. The
    patient is shown the exact fields that will be sent, on the consent
    step, and the only way to guarantee that what was shown is what goes
    is to send back what was shown.

    Two rules, both from real samples rather than taste:

    - `abhaNumber` is OMITTED ENTIRELY when empty. Our own Postman sample
      has it commented out, so absent is known-legal; `null` is not known
      to be, and this is not the place to find out.
    - `address.pincode` goes out LOWERCASE. NHA's sandbox sample spells it
      pinCode and our own collection spells it pincode; P21 reads both, so
      either is safe inbound, but matching our own collection is the safer
      bet on what ABDM's own validator wants.
    """
    out: dict[str, Any] = {}

    for key in ("abhaAddress", "name", "gender", "dayOfBirth", "monthOfBirth", "yearOfBirth", "phoneNumber"):
        value = patient.get(key)
        if value not in (None, ""):
            out[key] = value

    abha_number = patient.get("abhaNumber")
    if abha_number not in (None, ""):
        out["abhaNumber"] = abha_number

    address = patient.get("address")
    if isinstance(address, dict):
        cleaned = {
            "line": address.get("line"),
            "district": address.get("district"),
            "state": address.get("state"),
            # Accept either spelling in, emit the lowercase one out.
            "pincode": address.get("pincode") or address.get("pinCode"),
        }
        if any(v not in (None, "") for v in cleaned.values()):
            out["address"] = cleaned

    return out


# =============================================================================
# Share the profile  --  POST /patient-share/v3/share
# =============================================================================

def share_profile(
    settings: Settings,
    x_token: str,
    hip_id: str,
    counter_id: str,
    patient: dict[str, Any],
    request_id: str | None = None,
) -> AbdmResult:
    """
    Sends the patient's demographics to the facility they just scanned,
    via the Consent Manager.

    `hip_id` goes in BOTH metaData.hipId and (on the CM's side) the
    routing -- both Postman samples carry it in the body, so it is sent
    there even though the QR already implied it.

    `counter_id` is metaData.context, the counter string round-tripped out
    of the QR. P21 echoes it back in its acknowledgement, which is how the
    facility's own token board knows which queue the patient joined.

    UNCONFIRMED response -- see this module's banner. Expect a bare 2xx;
    parse nothing from it.

    `x_token` is the patient's session token. It is passed as a plaintext
    secret so that if ABDM ever echoes it back in a response body, it is
    scrubbed before the archived abdm_call_log row is written -- same
    discipline link_confirm() uses for the OTP.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/patient-share/v3/share"

    payload = {
        "intent": "PROFILE_SHARE",
        "metaData": {
            # hprId / latitude / longitude deliberately ABSENT -- see this
            # module's banner. They are the facility's, not the patient's.
            "hipId": hip_id,
            "context": counter_id,
        },
        "profile": {"patient": _clean_patient(patient)},
    }

    headers = _headers(x_token, settings.abdm_x_cm_id, settings.abdm_hiu_id, request_id=request_id)
    log_phase(f"Scan & Share: sharing profile with hip={hip_id} counter={counter_id}")
    return _execute(
        "/phr/scan-share/share",
        "POST",
        url,
        headers,
        payload,
        "PHR profile share",
        plaintext_secrets=(x_token,),
    )


# =============================================================================
# Poll for the token  --  GET /patient-share/v3/profile/getTokenDetails
# =============================================================================

def get_token_details(settings: Settings, x_token: str, limit: int = -1) -> AbdmResult:
    """
    Asks the CM for this patient's own share tokens.

    CANDIDATE B of the two ways the token could come back (the other being
    an inbound /api/v3/hiu/patient/on-share callback, see
    aegle_phr/callbacks/profile_share_services.py). This one is at least a
    documented endpoint with a saved Postman request, which is why the UI
    trusts it -- but its RESPONSE SHAPE IS UNCONFIRMED, with zero saved
    responses anywhere, so nothing here reads a field out of it. The body
    comes back verbatim and the screen renders it defensively.

    `limit=-1` is what the saved request sends; it reads as "no limit".

    NO X-HIU-ID on this call -- absent from the saved request, so not
    added. See this module's banner.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/patient-share/v3/profile/getTokenDetails"
    headers = _headers(x_token, settings.abdm_x_cm_id, hiu_id=None)

    log_phase(f"Scan & Share: fetching token details (limit={limit})")
    return _execute(
        "/phr/scan-share/token-details",
        "GET",
        url,
        headers,
        None,
        "PHR get share token details",
        params={"limit": limit},
        plaintext_secrets=(x_token,),
    )


# =============================================================================
# Reading the counter QR -- pure local parsing, no network
# =============================================================================

class ScannedQrError(ValueError):
    """The scanned text carried no facility id. Raised with a message meant to be shown to a person."""


def parse_scanned_qr(scanned: str) -> dict[str, str]:
    """
    Pulls the facility and counter out of whatever the camera decoded.

    DELIBERATELY HOST-AGNOSTIC. The sandbox QR points at
    phrsbx.abdm.gov.in/share-profile, but the production host is genuinely
    unknown (repo/server/config.py's own PHR_SHARE_PROFILE_BASE_URL comment
    records that phr.abdm.gov.in is a guess nobody has verified). Matching
    on the host would mean a QR that works everywhere except here. What
    identifies this as a share QR is the PARAMETERS, so that is what is
    matched on.

    Accepts, in practice:
        https://phrsbx.abdm.gov.in/share-profile?hip-id=X&counter-id=Y
        https://anything.example/whatever?counter-id=Y&hip-id=X   (order-free)
        hip-id=X&counter-id=Y                                     (bare query)
        ?hip-id=X&counter-id=Y

    HYPHENATED NAMES ARE CANONICAL -- that is what ABDM's own page uses and
    what repo/'s QR generator emits. camelCase and snake_case are tolerated
    as aliases purely so a QR from some other implementation fails with a
    real error rather than a misleading "no facility id" one.

    A MISSING counter-id IS NOT AN ERROR. It defaults to "", and the caller
    is told so. A facility that displays one QR for the whole reception
    desk rather than one per counter is a legitimate setup, and refusing to
    share for the sake of a queue label would be the wrong trade.

    Raises:
        ScannedQrError: when no facility id is present -- the one thing
            this genuinely cannot proceed without.
    """
    from urllib.parse import parse_qs, urlparse

    text = (scanned or "").strip()
    if not text:
        raise ScannedQrError("Nothing was scanned -- the QR code could not be read.")

    parsed = urlparse(text)
    query = parsed.query

    # A QR that encodes the params after a '#' rather than a '?' -- seen in
    # single-page-app links generally, not specifically here, but cheap to
    # survive.
    if not query and parsed.fragment and "=" in parsed.fragment:
        query = parsed.fragment.split("?", 1)[-1]

    # A bare query string, with or without a leading '?'.
    if not query:
        query = text.split("?", 1)[-1] if "?" in text else text

    params = parse_qs(query, keep_blank_values=True)

    def first(*names: str) -> str:
        for name in names:
            values = params.get(name)
            if values and values[0].strip():
                return values[0].strip()
        return ""

    hip_id = first("hip-id", "hipId", "hip_id")
    counter_id = first("counter-id", "counterId", "counter_id")

    if not hip_id:
        raise ScannedQrError(
            "That QR code is missing a facility id (hip-id), so there is nothing to share with. "
            "Check it is the counter QR at the reception desk and not some other code."
        )

    return {"hipId": hip_id, "counterId": counter_id, "raw": text}
