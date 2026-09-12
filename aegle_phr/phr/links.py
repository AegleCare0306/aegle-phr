"""
Get All Linked Records -- "already linked" care contexts for the
logged-in user's ABHA address (HIP-Initiated Linking, spec section 9;
the HIP side of that flow is already implemented server-side in repo/,
nothing new needed there). Aayush's own instruction: this comes BEFORE
User-Initiated Linking (spec section 10, discovering/linking NEW
records) -- that's explicitly the LAST chunk in this project, not
touched here.

THE SPEC DOCUMENTS THIS ENDPOINT TWICE, DISAGREEING WITH ITSELF -- a
judgment call, not a silent pick, same as every other spec/Postman
contradiction in this project:

  SS6.12 ("HIE-CM - Get All Links Records", Consent Manager section) --
  same URL, its own header table (REQUEST-ID/TIMESTAMP/X-CM-ID/
  X-AUTH-TOKEN, no Authorization at all), and a response example shaped
  like a token-queue/counter record (tokenNumber, expiresIn as a queue
  slot duration, counterCode) -- nothing about "links" in it at all.

  SS9.3.5 ("GET All Link records", HIP-Initiated Linking section) --
  the SAME URL, a header table that additionally lists Authorization,
  and a response example shaped like {"patient": {"id", "links": [...]}}
  -- a patient object containing HIP links, each with its own
  careContexts array. This is coherent with what "records linked to my
  account" should actually look like.

TRUSTED, NOW CONFIRMED LIVE (Aayush, directly, first real run of this
chunk): SS9.3.5's response shape. SS6.12's example reads as a copy-paste
artifact from an unrelated part of the spec (a token/counter shape has
no business being the response to a "get my links" call), and it's the
one table that's missing Authorization -- an odd omission given every
other GET in this whole project sends it. The real sandbox response
matches SS9.3.5's `{"patient": {"links": [...]}}` shape -- confirmed by
the frontend's own SS9.3.5-shaped parser (testui's HomeScreen.tsx)
successfully rendering real records rather than falling back to a raw
dump. GetAllLinkedRecordsResponse below documents that shape as a
CONTRACT, not a gate -- get_all_linked_records() itself still returns
ABDM's response completely unparsed (same "trust an incomplete/
contradictory spec least, a real capture most" rule as every other
module in this project), so nothing here would misparse a future
response that ever looked different.

NO SAVED POSTMAN EXAMPLE RESPONSE EXISTED for this request anywhere in
Aayush's workspace before this chunk (only the request itself, under
"PHR" -> "Consent Manager" -> "HIU & HIP" -> "links") -- this endpoint
had never actually been called against the sandbox before this chunk's
own live run settled the SS6.12-vs-SS9.3.5 question above. See the
project's README.md captured-shapes section for the confirmed shape.

URL PARAMETER: the Postman-saved request uses `?limit=-1` (all records)
embedded in the query string, NOT SS9.3.5's own `limit=100` example --
trusted over the spec's example for the same reason this project always
prefers a captured request over a spec illustration. Defaulted to -1
here, overridable by the caller.

HOST: this is a HIE-CM (Health Information Exchange - Consent Manager)
endpoint, not an ABHA-identity one -- it lives under settings.
abdm_hiecm_base_url (confirmed against repo/server/config.py's own
HIECM_BASE_URL during P3's research), NOT abdm_abha_base_url every other
module in aegle_phr/phr/ hits. That field has sat unused in settings.py
since it was added; this is its first real consumer.

HEADERS -- SEND THE SUPERSET, SAME CALL THIS PROJECT ALWAYS MAKES WHEN
THE SPEC DISAGREES WITH ITSELF (see aegle_phr/phr/profile.py's own
_headers(), which sends both Authorization and X-Token for the identical
reason): Authorization (gateway bearer token), X-AUTH-TOKEN (the
session token from session.ts -- NOT named X-Token here, a genuinely
different header name from profile.py/profile_link.py despite carrying
the same value), X-CM-ID (settings.abdm_x_cm_id, already "sbx" and
already sitting unused the same way abdm_hiecm_base_url was), REQUEST-ID,
TIMESTAMP. SS9.3.5's own table (the one this module trusts) already
lists all five as required/expected, so this costs nothing extra even
if one turns out unnecessary.

NO ENCRYPTION: a plain GET with no request body -- nothing here calls
get_public_certificate()/encrypt_value(), and none of this project's
certificate rules apply to this module at all.

RETRY: default classifier. Read-only, side-effect-free, safe to retry
freely -- also why this is the lowest-risk live call in this project so
far (no OTP consumed, no state changed on ABDM's side).
"""

import time
from typing import Any

import requests
from pydantic import BaseModel

from abdm_core.http import call_with_retry, generate_request_id, generate_timestamp
from abdm_core.observability.flow_logger import log_api_call, log_error, log_phase
from abdm_core.session import get_gateway_token

from aegle_phr.phr.call_log import archive
from aegle_phr.phr.enrollment import AbdmResult
from aegle_phr.settings import Settings

_TIMEOUT_SECONDS = 30


class LinkedHip(BaseModel):
    """SS9.3.5's own nested `hip` object -- documented as a contract, not used to gate the response."""

    id: str | None = None
    name: str | None = None
    type: str | None = None


class LinkedCareContext(BaseModel):
    referenceNumber: str | None = None
    display: str | None = None


class LinkedRecord(BaseModel):
    hip: LinkedHip | None = None
    referenceNumber: str | None = None
    display: str | None = None
    hiType: str | None = None
    careContexts: list[LinkedCareContext] = []
    dateCreated: str | None = None


class LinkedPatient(BaseModel):
    id: str | None = None
    links: list[LinkedRecord] = []


class GetAllLinkedRecordsResponse(BaseModel):
    """
    SS9.3.5's documented shape ({"patient": {"id", "links": [...]}}) --
    trusted over SS6.12's contradicting example, see module banner. NOW
    CONFIRMED live against the real sandbox. Recorded as a CONTRACT only
    -- get_all_linked_records() itself returns ABDM's raw body untouched,
    same convention as every other module in this project.
    """

    patient: LinkedPatient | None = None


def _headers(x_auth_token: str, x_cm_id: str) -> dict[str, str]:
    """
    Authorization + X-AUTH-TOKEN + X-CM-ID, always -- see module banner's
    HEADERS section for why this is a different header set (and a
    different literal session-token header NAME) from every other module
    in aegle_phr/phr/.
    """
    return {
        "REQUEST-ID": generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-AUTH-TOKEN": x_auth_token,
        "X-CM-ID": x_cm_id,
    }


def _parse(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def get_all_linked_records(settings: Settings, x_auth_token: str, limit: int = -1) -> AbdmResult:
    """
    GET {abdm_hiecm_base_url}/hip/v3/link/patient/links?limit={limit} --
    see module banner for the full SS6.12-vs-SS9.3.5 contradiction this
    resolves, and for why `limit=-1` (all records) is the default,
    matching the one real saved Postman request rather than the spec's
    own `limit=100` example.

    x_auth_token: the logged-in session's token (session.ts's own
    getSessionToken()) -- carried in the X-AUTH-TOKEN header, NOT
    X-Token like profile.py/profile_link.py use for the identical value.

    RESPONSE SHAPE CONFIRMED LIVE (this chunk's own first run): matches
    SS9.3.5, not SS6.12 -- see module banner. Still returned completely
    raw and unparsed regardless -- see GetAllLinkedRecordsResponse's own
    docstring -- so a future response that ever looked different would
    still pass through cleanly rather than being misparsed.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/hip/v3/link/patient/links"
    params = {"limit": limit}
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)

    log_phase("Fetching all linked records")
    route = "/phr/links/get-all"
    started = time.monotonic()

    try:
        response = call_with_retry(
            lambda: requests.get(url, headers=headers, params=params, timeout=_TIMEOUT_SECONDS),
            description="PHR get all linked records",
        )
    except requests.exceptions.RequestException as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"Get all linked records failed: {exc}")
        archive(route, url, {"limit": limit}, None, None, duration_ms, str(exc), ())
        return AbdmResult(status_code=None, body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    body = _parse(response)

    log_api_call("PHR get all linked records", url, response.status_code)
    archive(route, url, {"limit": limit}, response.status_code, body, duration_ms, None, ())

    return AbdmResult(status_code=response.status_code, body=body)
