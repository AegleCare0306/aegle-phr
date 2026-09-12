"""
User-Initiated Linking (spec §10.3.1-§10.3.12) -- discover / link-init /
link-confirm, the three outbound HIU-role calls that let a patient find and
link care contexts a HIP hasn't already linked via HIP-Initiated Linking
(spec §9, aegle_phr/phr/links.py). See
CC_PROMPT_P15_user_initiated_linking.md for the full task spec; its own
research (re-read from CC_PROMPT_P3_provider_search_and_uil.md, not
re-derived) is what the header/body/host choices below come from.

HEADERS -- a genuinely different family from every other patient-facing
module in aegle_phr/phr/: Authorization (gateway, as always) + X-AUTH-TOKEN
(the LITERAL header name -- NOT X-token like every Profile-family call,
see links.py/consent.py for that other convention) + X-CM-ID + X-HIU-ID
(this app's own HIU identity) + REQUEST-ID/TIMESTAMP.

X-HIU-ID = settings.abdm_hiu_id, set to CLIENT_ID (SBXID_046112) -- this
project's own established self-service pattern, independently confirmed
three other ways already (Data Flow's self-view fetch, Subscription Flow's
self-subscription, Consent Auto-Approval's own hiu.id correction -- see
that setting's own docstring and .env's own comment). STILL FLAG FOR LIVE
CONFIRMATION before link_init() specifically (the OTP-consuming step) --
same discipline this project applied the last two times this exact value
was reused for a new endpoint family.

NO ENCRYPTION ANYWHERE IN THIS FAMILY -- confirmed from the spec's own
examples across all three calls (unverifiedIdentifiers[].value,
transactionId, linkRefNumber, even the confirm step's token/OTP itself are
all plain values, never a `{{encrypted ...}}` placeholder the way every
other OTP flow in this project uses). Flag for live re-verification on the
first real call, same discipline as every other "no encryption here"
reading in this project -- don't build encryption in preemptively.

Same per-module _headers()/_execute() shape as every other module here
(subscription.py, consent.py) -- duplicated, not imported, per this
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


def _headers(x_auth_token: str, x_cm_id: str, hiu_id: str, request_id: str | None = None) -> dict[str, str]:
    """
    The three outbound UIL calls' own header shape. `request_id`:
    caller-supplied so the route handler can save the pending
    UilLinkRequest row BEFORE the call completes, to correlate the
    eventual callback back to it -- same reason subscription.py's own
    _requester_headers() takes one (see that function's own docstring).
    A fresh one is generated here only when the caller doesn't need to
    pre-save anything (there currently isn't such a caller in this
    module, but the fallback keeps this function usable standalone).
    """
    return {
        "Content-Type": "application/json",
        "REQUEST-ID": request_id or generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-AUTH-TOKEN": x_auth_token,
        "X-CM-ID": x_cm_id,
        "X-HIU-ID": hiu_id,
    }


def _parse(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _execute(
    route: str,
    url: str,
    headers: dict[str, str],
    payload: Any,
    description: str,
    plaintext_secrets: tuple[str, ...] = (),
) -> AbdmResult:
    """
    POST-only -- all three UIL calls are POSTs (confirmed, see the task
    spec's own header/body tables). Mirrors subscription.py's own
    _execute(), minus the GET/PUT branches it needed for that section's
    own lookups/edit -- nothing here is a lookup or an edit.
    """
    started = time.monotonic()

    def attempt() -> requests.Response:
        return requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT_SECONDS)

    try:
        response = call_with_retry(attempt, description=description)
    except requests.exceptions.RequestException as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"{description} failed: {exc}")
        archive(route, url, payload, None, None, duration_ms, str(exc), plaintext_secrets)
        return AbdmResult(status_code=None, body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    body = _parse(response)

    log_api_call(description, url, response.status_code)
    archive(route, url, payload, response.status_code, body, duration_ms, None, plaintext_secrets)

    return AbdmResult(status_code=response.status_code, body=body)


# =============================================================================
# 10.3.1 -- Discover  --  POST /user-initiated-linking/v3/patient/care-context/discover
# =============================================================================

def discover(
    settings: Settings,
    x_token: str,
    hip_id: str,
    abha_address: str,
    request_id: str | None = None,
) -> AbdmResult:
    """
    Response: bare 202 Accepted, nothing useful in the body -- the real
    answer (matched care contexts, or an error like ABDM-1010 "Patient not
    found") arrives later as the on-discover callback
    (aegle_phr/callbacks/uil_services.py's own handle_on_discover()),
    correlated by response.requestId equalling the REQUEST-ID sent here.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/user-initiated-linking/v3/patient/care-context/discover"
    # LIVE-CONFIRMED CORRECTION (2026-09-05): the task spec's own prose
    # (CC_PROMPT_P3_provider_search_and_uil.md) documented this as a flat
    # "hipId" field, matching repo/server/linking.py's own commented-out
    # (and NEVER actually run) reference implementation -- both wrong, or
    # at least not what THIS sandbox actually wants. A real discover() call
    # with a flat "hipId" got back a real 400: {"code": "ABDM-9999: ",
    # "message": "HIP ID is mandatory"} -- despite hipId being present,
    # non-empty, and correctly named, confirmed by reading the exact
    # archived request body back out of abdm_call_log. Every OTHER already-
    # proven ABDM call in this project nests an identifier as an object
    # instead ({"hiu": {"id": ...}} in subscription.py's own
    # initiate_subscription_request() and data_flow.py's own CLIENT_ID
    # usage, {"hip": {"id": ...}} in consent.py's own documented shape) --
    # nested "hip": {"id": hip_id} is what this project's own real,
    # working precedent says this family should look like, not a guess.
    payload = {
        "hip": {"id": hip_id},
        "unverifiedIdentifiers": [{"type": "ABHA_ADDRESS", "value": abha_address}],
    }
    headers = _headers(x_token, settings.abdm_x_cm_id, settings.abdm_hiu_id, request_id=request_id)
    log_phase(f"UIL discover: hip={hip_id} abhaAddress={abha_address}")
    return _execute("/phr/uil/discover", url, headers, payload, "PHR UIL discover")


# =============================================================================
# 10.3.5 -- Link init  --  POST /user-initiated-linking/v3/link/care-context/init
# =============================================================================

def link_init(
    settings: Settings,
    x_token: str,
    transaction_id: str,
    abha_address: str,
    patient_matches: list[dict[str, Any]],
    request_id: str | None = None,
) -> AbdmResult:
    """
    Called once discover's own callback has returned real matches the
    patient wants to link. `patient_matches` is the SAME patient[]
    (each with its own careContexts[]) shape discover's own callback
    returned -- echoed back, not new data (the patient is confirming which
    of the discovered records to link, not supplying anything ABDM doesn't
    already know).

    SENDS A REAL OTP to the patient's real registered mobile, via the HIP
    -- same live-testing caution as every other OTP-sending call in this
    project: only call this with the caller's own explicit go-ahead.
    Response: bare 202 Accepted; the usable linkRefNumber arrives later via
    the on-init callback.

    LIVE-CONFIRMED CORRECTION (2026-09-05), same source/reason as
    discover()'s own fix: the task spec's own prose said this body carries
    `abhaAddress` alongside transactionId/patient -- but the real saved
    Postman request (PHR&HIECM collection, "User Initiated Linking/03
    link-init") sends ONLY `{transactionId, patient}`, no abhaAddress
    field at all. Matched to that real example instead of the spec text.
    `abha_address` stays a parameter here (not sent to ABDM) because the
    caller (the /phr/uil/link-init route) still needs it to populate the
    new UilLinkRequest row's own abha_address column.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/user-initiated-linking/v3/link/care-context/init"
    payload = {
        "transactionId": transaction_id,
        "patient": patient_matches,
    }
    headers = _headers(x_token, settings.abdm_x_cm_id, settings.abdm_hiu_id, request_id=request_id)
    log_phase(f"UIL link-init: transactionId={transaction_id} -- SENDS A REAL OTP")
    return _execute("/phr/uil/link-init", url, headers, payload, "PHR UIL link-init")


# =============================================================================
# 10.3.9 -- Link confirm  --  POST /user-initiated-linking/v3/link/care-context/confirm
# =============================================================================

def link_confirm(
    settings: Settings,
    x_token: str,
    token: int,
    link_ref_number: str,
    request_id: str | None = None,
) -> AbdmResult:
    """
    `token`: the OTP the patient just typed, as a NUMBER per the spec's own
    example (not a string) -- caller's responsibility to convert before
    calling this. Response: bare 202 Accepted; the final confirmed
    patient[] (now genuinely linked) arrives later via the on-confirm
    callback.

    `token` is the plaintext OTP -- passed to _execute() as a
    plaintext_secret so it is scrubbed from the archived abdm_call_log row,
    same redaction discipline as every other OTP-consuming call in this
    project.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/user-initiated-linking/v3/link/care-context/confirm"
    payload = {"token": token, "linkRefNumber": link_ref_number}
    headers = _headers(x_token, settings.abdm_x_cm_id, settings.abdm_hiu_id, request_id=request_id)
    log_phase(f"UIL link-confirm: linkRefNumber={link_ref_number}")
    return _execute("/phr/uil/link-confirm", url, headers, payload, "PHR UIL link-confirm", plaintext_secrets=(str(token),))
