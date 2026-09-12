"""
Subscription Flow (spec §8) -- all 18 endpoints + Health Locker. See
CC_PROMPT_P13_subscription_flow_full_build.md for the full task spec this
module implements.

WHY THIS APP PLAYS BOTH ROLES: spec §8.1 -- a Health locker/PHR "should
initiate subscription requests so that it receives notifications/alerts
whenever new information is available" (categories LINK/DATA), and "Subscription
will get auto approve for health locker for all HIPs and for all HI types."
Every endpoint that says "invoked by the patient/user through the PHR
application" means OUR OWN app's UI -- this project IS the PHR application
the spec keeps referring to. So this module has TWO header shapes:

  - REQUESTER calls (init, and both on-notify acks) -- confirmed via the
    real "PHR&HIECM" Postman collection's own saved requests: NONE of
    these three carry X-AUTH-TOKEN, only REQUEST-ID/TIMESTAMP/X-CM-ID +
    the gateway Authorization token. This matches consent's own analogous
    HIU-role calls (repo/server/hiu_consent.py's initiate_consent_request()/
    send_consent_hiu_on_notify(), neither of which take a patient token
    either) -- a subscription/consent INIT is something the HIU/locker
    does about a patient, not something the patient's own session does.
  - PATIENT-FACING calls (approve/deny/edit, every GET lookup, setup-locker,
    enable/disable) -- these DO carry X-AUTH-TOKEN, same _headers() shape
    as consent.py's own.

SOURCE OF TRUTH FOR EVERY BODY/URL BELOW: the spec docx (`ABHA_PHR_V3_Documents`)
section 8, cross-checked against the real "PHR&HIECM" Postman collection's
"Subscription and Health locker" folder -- both supplied directly by Aayush
for this pass (the earlier attempt to build this had neither on disk).
Postman wins wherever the two disagree, same standing practice this whole
project has used since P1-J. Two real disagreements found and resolved:

  1. 8.3.7 (Deny): the spec's own URL text reads
     `/api/hiecm/subscriptionrequests/v3/{id}/deny` (no hyphen) -- but
     Postman's real saved request uses the HYPHENATED
     `/api/hiecm/subscription-requests/v3/{id}/deny`, matching Approve's
     own path exactly. Used Postman's (hyphenated) -- the spec's own text
     is very likely a typo (no other endpoint in this whole section drops
     the hyphen), not a genuine different form.
  2. 8.3.14 (details by subscription id): the spec's own text prints the
     IDENTICAL url to 8.3.13 (`.../v3/request/{id}`) -- certainly a
     copy-paste error, since two different lookup keys sharing one path
     makes no sense. Postman's real saved request uses
     `/api/hiecm/subscription-requests/v3/{subscriptionID}` (no `/request/`
     segment) -- used that.

NEVER RUN AGAINST THE SANDBOX YET (this whole module, all 15 outbound
functions) -- every response shape below is the spec's/Postman's own
documented example, not a live capture. Same discipline as consent.py:
every function still returns ABDM's raw body completely unparsed, so a
live run that reveals a different shape loses nothing.
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

# The 8 confirmed hiTypes, same literal list this project uses everywhere
# else a caller needs "every hiType" (e.g. data_flow.py's own
# _SELF_VIEW_HI_TYPES) -- kept as a local copy per this project's own
# per-module convention rather than a shared import.
ALL_HI_TYPES = [
    "Prescription", "DiagnosticReport", "OPConsultation", "DischargeSummary",
    "ImmunizationRecord", "HealthDocumentRecord", "WellnessRecord", "Invoice",
]


def _requester_headers(x_cm_id: str, request_id: str | None = None) -> dict[str, str]:
    """
    REQUESTER-role calls only (init, both on-notify acks) -- CONFIRMED,
    not guessed: the real Postman collection's saved requests for these
    three specifically omit X-AUTH-TOKEN, carrying only REQUEST-ID/
    TIMESTAMP/X-CM-ID plus the gateway Authorization token. See this
    module's own banner for why that's structurally correct (an HIU/
    locker action about a patient, not the patient's own session).

    `request_id`: normally a fresh REQUEST-ID is generated here (every
    OTHER call in this project's own convention) -- but
    initiate_subscription_request() below accepts a CALLER-supplied one
    instead, since ensure_self_subscription() (data_flow.py) needs to
    persist the pending row's key BEFORE the call completes, to
    correlate the eventual 8.3.3 callback back to it (mirrors repo/
    server/hiu_consent.py's own initiate_consent_request(), which
    generates its REQUEST-ID first, saves the pending session, THEN
    makes the call, for the identical reason).
    """
    return {
        "Content-Type": "application/json",
        "REQUEST-ID": request_id or generate_request_id(),
        "TIMESTAMP": generate_timestamp(),
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-CM-ID": x_cm_id,
    }


def _headers(x_auth_token: str, x_cm_id: str) -> dict[str, str]:
    """PATIENT-FACING calls -- identical shape to consent.py's own _headers()."""
    return {
        "Content-Type": "application/json",
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


def _execute(
    route: str,
    method: str,
    url: str,
    headers: dict[str, str],
    payload: Any,
    description: str,
    params: dict[str, Any] | None = None,
) -> AbdmResult:
    """
    Shared plumbing for all 15 outbound calls -- mirrors consent.py's own
    _execute(), extended with PUT (needed for 8.3.9 Edit, the one PUT in
    this whole section -- consent.py's own version only ever needed
    GET/POST). Never calls raise_for_status(): a 4xx from ABDM (e.g. a
    patient denying an already-decided request) is an expected, handled
    outcome, not an exception.
    """
    started = time.monotonic()

    def attempt() -> requests.Response:
        if method == "GET":
            return requests.get(url, headers=headers, params=params, timeout=_TIMEOUT_SECONDS)
        if method == "PUT":
            return requests.put(url, json=payload, headers=headers, timeout=_TIMEOUT_SECONDS)
        return requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT_SECONDS)

    try:
        response = call_with_retry(attempt, description=description)
    except requests.exceptions.RequestException as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_error(f"{description} failed: {exc}")
        archive(route, url, payload if payload is not None else (params or {}), None, None, duration_ms, str(exc), ())
        return AbdmResult(status_code=None, body=None, error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    body = _parse(response)

    log_api_call(description, url, response.status_code)
    archive(route, url, payload if payload is not None else (params or {}), response.status_code, body, duration_ms, None, ())

    return AbdmResult(status_code=response.status_code, body=body)


# =============================================================================
# 8.3.2 -- Init subscription request  --  POST /subscription-requests/v3/init
# =============================================================================

def initiate_subscription_request(
    settings: Settings,
    patient_id: str,
    hiu_id: str,
    categories: list[str],
    period_from: str,
    period_to: str,
    hips: list[dict[str, str]] | None = None,
    purpose_text: str = "Care Management",
    purpose_code: str = "CAREMGT",
    purpose_ref_uri: str = "www.abdm.gov.in",
    request_id: str | None = None,
) -> AbdmResult:
    """
    REQUESTER call -- no X-AUTH-TOKEN (see _requester_headers()'s own
    docstring). `hiu_id` is CLIENT_ID for the self-subscription case (this
    app subscribing to be notified about a patient's OWN new data -- see
    ensure_self_subscription() in data_flow.py), but left caller-supplied
    since a real HIU-facing subscription would pass a different value.
    `hips` is optional per the spec's own body table (Yes for `hips` was
    actually marked "NO" in the spec's own body-parameter table, despite
    Postman's saved example including one facility) -- omitted entirely
    (not sent as an empty list) when None, to match "subscribe across
    every HIP" rather than an empty, presumably-nothing-matches list.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/subscription-requests/v3/init"
    subscription: dict[str, Any] = {
        "purpose": {"text": purpose_text, "code": purpose_code, "refUri": purpose_ref_uri},
        "patient": {"id": patient_id},
        "hiu": {"id": hiu_id},
        "categories": categories,
        "period": {"from": period_from, "to": period_to},
    }
    if hips is not None:
        subscription["hips"] = hips
    payload = {"subscription": subscription}
    headers = _requester_headers(settings.abdm_x_cm_id, request_id=request_id)
    log_phase(f"Initiating subscription request for patient {patient_id} (hiu={hiu_id}, categories={categories})")
    return _execute("/phr/subscription/init", "POST", url, headers, payload, "PHR subscription init")


# =============================================================================
# 8.3.6 -- Ack HIU received on-init callback  --  POST .../hiu/on-notify
# =============================================================================

def ack_subscription_on_init(settings: Settings, subscription_request_id: str, response_request_id: str) -> AbdmResult:
    """
    REQUESTER call -- no X-AUTH-TOKEN. `response_request_id` is ABDM's own
    REQUEST-ID header value from the INBOUND 8.3.3 callback being
    acknowledged, echoed back verbatim -- CONFIRMED via the proven,
    already-live analogous consent pattern (repo/server/hiu_consent.py's
    send_consent_hiu_on_notify(): "request_id ... echoed back as
    response.requestId, matching the ack convention used elsewhere in
    this codebase") -- NOT a freshly-generated id, and NOT the original
    8.3.2 init call's own REQUEST-ID.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/subscription-requests/v3/hiu/on-notify"
    payload = {
        "acknowledgement": {"status": "OK", "subscriptionRequestId": subscription_request_id},
        "response": {"requestId": response_request_id},
    }
    headers = _requester_headers(settings.abdm_x_cm_id)
    log_phase(f"Acking subscription on-init for subscriptionRequestId={subscription_request_id}")
    return _execute("/phr/subscription/ack-on-init", "POST", url, headers, payload, "PHR subscription ack on-init")


# =============================================================================
# 8.3.4 -- Approve subscription request  --  POST .../{id}/approve
# =============================================================================

def approve_subscription_request(
    settings: Settings,
    x_auth_token: str,
    subscription_request_id: str,
    is_applicable_for_all_hips: bool,
    hi_types: list[str],
    categories: list[str],
    period_from: str,
    period_to: str,
    purpose_text: str = "Care Management",
    purpose_code: str = "CAREMGT",
    purpose_ref_uri: str = "www.abdm.gov.in",
    hip_id: str | None = None,
    hip_name: str | None = None,
    excluded_sources: list[dict[str, Any]] | None = None,
) -> AbdmResult:
    """
    PATIENT-FACING call. Body shape confirmed via Postman's real saved
    "02 approve-subscription-request" example -- includedSources[0] there
    has NO `hip` key at all (unlike the spec's own body table, which shows
    an OPTIONAL `hip`), so `hip_id`/`hip_name` stay optional here too,
    included only when isApplicableForAllHIPs is false and a caller
    actually supplies them.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/subscription-requests/v3/{subscription_request_id}/approve"
    source: dict[str, Any] = {
        "hiTypes": hi_types,
        "purpose": {"text": purpose_text, "code": purpose_code, "refUri": purpose_ref_uri},
        "categories": categories,
        "period": {"from": period_from, "to": period_to},
    }
    if hip_id is not None:
        source["hip"] = {"id": hip_id, "name": hip_name} if hip_name else {"id": hip_id}
    payload = {
        "isApplicableForAllHIPs": is_applicable_for_all_hips,
        "includedSources": [source],
        "excludedSources": excluded_sources or [],
    }
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase(f"Approving subscription request {subscription_request_id}")
    return _execute("/phr/subscription/approve", "POST", url, headers, payload, "PHR subscription approve")


# =============================================================================
# 8.3.7 -- Deny subscription request  --  POST .../{id}/deny
# =============================================================================

def deny_subscription_request(settings: Settings, x_auth_token: str, subscription_request_id: str, reason: str) -> AbdmResult:
    """
    PATIENT-FACING call. URL uses the HYPHENATED `subscription-requests`
    segment (Postman-confirmed, contradicting the spec's own typo'd text)
    -- see this module's own banner for the full discrepancy note.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/subscription-requests/v3/{subscription_request_id}/deny"
    payload = {"reason": reason}
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase(f"Denying subscription request {subscription_request_id}")
    return _execute("/phr/subscription/deny", "POST", url, headers, payload, "PHR subscription deny")


# =============================================================================
# 8.3.9 -- Edit subscription  --  PUT .../patients/{approved_subscription_id}
# =============================================================================

def edit_subscription(
    settings: Settings,
    x_auth_token: str,
    approved_subscription_id: str,
    hiu_id: str,
    is_applicable_for_all_hips: bool,
    hi_types: list[str],
    categories: list[str],
    period_from: str,
    period_to: str,
    purpose_text: str = "Care Management",
    purpose_code: str = "CAREMGT",
    purpose_ref_uri: str = "www.abdm.gov.in",
    excluded_sources: list[dict[str, Any]] | None = None,
) -> AbdmResult:
    """
    PATIENT-FACING call, the only PUT in this whole module. Body shape
    (top-level `hiuId` + a nested `subscriptionEditAndApprovalRequest`,
    itself shaped exactly like Approve's own body) confirmed verbatim via
    Postman's real saved "07 edit-subscription" example. Spec's own words:
    "user can change date range. HIP/HI type can't be edited" -- hi_types
    is still a required field on the wire either way (Postman's own
    example resends the full 8-type list), so this doesn't special-case it.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/subscription-requests/v3/patients/{approved_subscription_id}"
    payload = {
        "hiuId": hiu_id,
        "subscriptionEditAndApprovalRequest": {
            "isApplicableForAllHIPs": is_applicable_for_all_hips,
            "includedSources": [
                {
                    "hiTypes": hi_types,
                    "purpose": {"text": purpose_text, "code": purpose_code, "refUri": purpose_ref_uri},
                    "categories": categories,
                    "period": {"from": period_from, "to": period_to},
                }
            ],
            "excludedSources": excluded_sources or [],
        },
    }
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase(f"Editing subscription {approved_subscription_id}")
    return _execute("/phr/subscription/edit", "PUT", url, headers, payload, "PHR subscription edit")


# =============================================================================
# 8.3.12 -- Ack HIU received care-context notify  --  POST .../hiu/care-context/on-notify
# =============================================================================

def ack_subscription_care_context_notify(settings: Settings, event_id: str, response_request_id: str) -> AbdmResult:
    """
    REQUESTER call -- no X-AUTH-TOKEN. Same echo convention as
    ack_subscription_on_init() above: `response_request_id` is ABDM's own
    REQUEST-ID header from the inbound 8.3.11 callback being acknowledged.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/subscription-requests/v3/hiu/care-context/on-notify"
    payload = {
        "acknowledgement": {"status": "OK", "eventId": event_id},
        "response": {"requestId": response_request_id},
    }
    headers = _requester_headers(settings.abdm_x_cm_id)
    log_phase(f"Acking subscription care-context notify for eventId={event_id}")
    return _execute("/phr/subscription/ack-care-context-notify", "POST", url, headers, payload, "PHR subscription ack care-context notify")


# =============================================================================
# 8.3.1 -- Get all subscription requests  --  GET .../requests
# =============================================================================

def get_all_subscription_requests(settings: Settings, x_auth_token: str, limit: int = 10, offset: int = 0, status: str = "ALL") -> AbdmResult:
    """PATIENT-FACING call. Params confirmed via Postman's own saved query string."""
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/subscription-requests/v3/requests"
    params = {"limit": limit, "offset": offset, "status": status}
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase("Fetching all subscription requests")
    return _execute("/phr/subscription/requests/get-all", "GET", url, headers, None, "PHR get all subscription requests", params=params)


# =============================================================================
# 8.3.13 -- Subscription details by REQUEST id  --  GET .../request/{id}
# =============================================================================

def get_subscription_details_by_request_id(settings: Settings, x_auth_token: str, subscription_request_id: str) -> AbdmResult:
    """PATIENT-FACING call. URL confirmed identical in the spec AND Postman -- no discrepancy here, only 8.3.14 (below) has one."""
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/subscription-requests/v3/request/{subscription_request_id}"
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase(f"Fetching subscription details by request id {subscription_request_id}")
    return _execute("/phr/subscription/details-by-request-id", "GET", url, headers, None, "PHR get subscription details by request id")


# =============================================================================
# 8.3.14 -- Subscription details by SUBSCRIPTION id  --  GET .../{id}
# =============================================================================

def get_subscription_details_by_subscription_id(settings: Settings, x_auth_token: str, subscription_id: str) -> AbdmResult:
    """
    PATIENT-FACING call. URL is Postman's (`.../v3/{subscriptionID}`, no
    `/request/` segment) NOT the spec's own text (which duplicates 8.3.13's
    URL verbatim -- a copy-paste error) -- see this module's own banner.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/subscription-requests/v3/{subscription_id}"
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase(f"Fetching subscription details by subscription id {subscription_id}")
    return _execute("/phr/subscription/details-by-subscription-id", "GET", url, headers, None, "PHR get subscription details by subscription id")


# =============================================================================
# 8.3.15 -- Get all subscription+consent requests  --  GET .../patients/requests
# =============================================================================

def get_all_patient_requests(
    settings: Settings,
    x_auth_token: str,
    consent_limit: int = 10,
    consent_offset: int = 0,
    subscription_limit: int = 10,
    subscription_offset: int = 0,
    status: str = "ALL",
) -> AbdmResult:
    """PATIENT-FACING call. All 5 query param names confirmed verbatim via Postman's own saved query string."""
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/subscription-requests/v3/patients/requests"
    params = {
        "consentLimit": consent_limit,
        "consentOffset": consent_offset,
        "subscriptionLimit": subscription_limit,
        "subscriptionOffset": subscription_offset,
        "status": status,
    }
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase("Fetching all subscription+consent requests")
    return _execute("/phr/subscription/patients/requests", "GET", url, headers, None, "PHR get all patient subscription+consent requests", params=params)


# =============================================================================
# 8.3.16 -- Get patient's subscribed lockers  --  GET .../patients/lockers
# =============================================================================

def get_patient_subscribed_lockers(settings: Settings, x_auth_token: str, include_inactive: bool = True) -> AbdmResult:
    """PATIENT-FACING call."""
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/subscription-requests/v3/patients/lockers"
    params = {"includeInactive": str(include_inactive).lower()}
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase("Fetching patient's subscribed lockers")
    return _execute("/phr/subscription/patients/lockers/get-all", "GET", url, headers, None, "PHR get patient subscribed lockers", params=params)


# =============================================================================
# 8.3.17 -- Locker details by locker id  --  GET .../patients/lockers/{id}
# =============================================================================

def get_locker_details(settings: Settings, x_auth_token: str, locker_id: str) -> AbdmResult:
    """PATIENT-FACING call."""
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/subscription-requests/v3/patients/lockers/{locker_id}"
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase(f"Fetching locker details for locker {locker_id}")
    return _execute("/phr/subscription/patients/lockers/get-one", "GET", url, headers, None, "PHR get locker details", params=None)


# =============================================================================
# 8.3.18 -- Setup Locker  --  POST .../setup-locker
# =============================================================================

def setup_locker(settings: Settings, x_auth_token: str, locker_id: str) -> AbdmResult:
    """
    PATIENT-FACING call. NEW HEADER this project has never sent before:
    X-LOCKER-ID. See R2 in CC_PROMPT_P13_subscription_flow_full_build.md --
    whether CLIENT_ID is genuinely registered as a HEALTH_LOCKER type is
    UNCONFIRMED; this function doesn't guess which value is right, it just
    takes `locker_id` as a caller-supplied string (the UI/bootstrap caller
    decides what to try) and logs the exact request/response either way so
    a live 4xx tells Aayush definitively whether registration is the
    blocker. No documented request body anywhere (spec or Postman) -- sent
    as an empty object, matching consent.py's own disable/enable precedent
    for a header-only action.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/subscription-requests/v3/setup-locker"
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    headers["X-LOCKER-ID"] = locker_id
    log_phase(f"Setting up health locker, X-LOCKER-ID={locker_id}")
    return _execute("/phr/subscription/setup-locker", "POST", url, headers, {}, "PHR setup locker")


# =============================================================================
# Disable / Enable  --  Postman-only, not in the spec's 18 numbered items
# =============================================================================

def _set_subscription_state(settings: Settings, x_auth_token: str, subscription_id: str, enable: bool) -> AbdmResult:
    action = "enable" if enable else "disable"
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/subscription-requests/v3/{action}/{subscription_id}"
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    route = f"/phr/subscription/{action}"
    return _execute(route, "POST", url, headers, {}, f"PHR subscription {action}")


def disable_subscription(settings: Settings, x_auth_token: str, subscription_id: str) -> AbdmResult:
    """No documented request body (Postman's own saved example sends `{}`) -- see this module's own banner for the Postman-only provenance."""
    log_phase(f"Disabling subscription {subscription_id}")
    return _set_subscription_state(settings, x_auth_token, subscription_id, enable=False)


def enable_subscription(settings: Settings, x_auth_token: str, subscription_id: str) -> AbdmResult:
    """No documented request body (Postman's own saved example sends `{}`) -- see this module's own banner for the Postman-only provenance."""
    log_phase(f"Enabling subscription {subscription_id}")
    return _set_subscription_state(settings, x_auth_token, subscription_id, enable=True)
