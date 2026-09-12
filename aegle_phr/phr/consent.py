"""
Consent Manager -- all 11 patient-facing consent flows (spec §6.13-§6.22,
plus Approve, which exists in Postman only). This is the mechanism that
lets a patient control who gets to READ the data behind the care contexts
"View All Linked Records" (links.py) already shows -- it does not itself
fetch any health-record content (spec §7 "Data Flow", a separate, later
phase, not touched here).

SAME HOST/HEADER FAMILY AS links.py -- READ THAT MODULE FIRST, IT IS THE
TEMPLATE THIS ONE MIRRORS, not profile.py: settings.abdm_hiecm_base_url
(NOT abdm_abha_base_url), and _headers() below is links.py's own
_headers() copied near-verbatim (Authorization + X-AUTH-TOKEN + X-CM-ID +
REQUEST-ID + TIMESTAMP, sent as a superset the same way every prior
chunk sends a superset when the spec's own header tables disagree with
each other or are incomplete). NO ENCRYPTION anywhere in this module --
every one of these 11 calls is a plain JSON body or a plain GET; nothing
here calls get_public_certificate()/encrypt_value(), and none of this
project's certificate rules apply.

NONE OF THESE 11 CALLS HAVE EVER BEEN RUN AGAINST THE SANDBOX. Every
response shape documented below is either the spec's own example or
inferred from the request body alone -- each function's own docstring
says which. Every *Response model below is a CONTRACT for the frontend,
not a gate: every function still returns ABDM's raw body completely
unparsed, same discipline as links.py and every other module in this
project, so a live run that reveals a different shape loses nothing.

THE APPROVE ENDPOINT IS NOT IN THE SPEC PDF AT ALL. Confirmed real via
Postman's "PHR" collection -> "Consent Manager" -> "FETCH & MANAGE
CONSENT REQUESTS" folder, request 06 ("Approve"), the sole source for
its URL, method, and body shape -- see approve_consent_request()'s own
docstring for the full body. This is exactly the standing lesson this
project keeps re-learning (P1-J's mobile-linking/address-creation, this
chunk's own research): a spec PDF being silent on an endpoint does not
mean the endpoint doesn't exist -- check Postman before assuming a gap.

APPROVE-BODY DESIGN JUDGMENT CALL, FLAGGED HERE AND IN THE FRONTEND:
approving a consent request is not a bare "yes" -- the patient submits
back the SPECIFIC hip/careContexts/hiTypes/permission being granted, in
the exact `consents[]` shape Postman's saved request shows. This module
takes that shape as-is (a list of caller-supplied grants) and does not
itself decide what to submit. UPDATED (P8, 2026-09-02): the FRONTEND
(ConsentScreen.tsx) now builds this via an actual HIP + care-context
picker (sourced from Linked Records, spec §9) rather than having nothing
to submit at all -- #5's own confirmed live response never carries a
hip/careContexts to accept as-is, so patient choice of WHICH facility/
record(s) was never optional, only unbuilt. hiTypes/permission are still
submitted UNCHANGED from the request's own values (this part of the
original "full-acceptance" plan was always fine) -- only hip/careContexts
narrowing to a patient's own picked selection is new; narrowing hiTypes
itself per-HIP remains a documented nice-to-have, not built. See that
screen's own banner for the one known, flagged gap left in what the
picker can supply (patientReference).

CONSENT AUTO-APPROVAL -- REWRITTEN, NOT SPEC §6.13 AT ALL (P11, 2026-09-02):
the ORIGINAL auto_approve() implemented spec §6.13's own documented
endpoint (POST {abdm_hiecm_base_url}/consent/v3/auto/approve, patient's
raw session token as X-AUTH-TOKEN) -- always honestly flagged in its own
docstring as "UNCONFIRMED against a live capture." It turned out to be
flatly wrong, not just unconfirmed: a live-captured Postman example (ABDM
Collection -> Building PHR App -> Setup Subscriptions/Setup Auto-approval,
NOT the spec PDF) shows the real mechanism is a 3-call sequence under a
COMPLETELY DIFFERENT host (settings.abdm_cm_base_url = https://dev.abdm.gov.in/cm,
not .../api/hiecm) -- create a Consent PIN once, verify it to get a
short-lived temporaryToken, then set the actual policy using THAT token
(not the patient's own session token) as X-Auth-Token. See
create_consent_pin()/verify_consent_pin()/auto_approve()'s own docstrings
for the full mechanics. This is exactly the standing lesson this project
keeps re-learning about the spec PDF being an unreliable source for an
endpoint's real shape -- the difference here is the PDF wasn't SILENT
(the Approve-endpoint case), it documented something that plainly isn't
what ABDM's real sandbox does.

WHY THIS MATTERS BEYOND THIS ONE MANUAL TEST BUTTON: this project's own
self-view flow (aegle_phr/phr/data_flow.py's request_self_view_consent(),
called from HomeScreen.tsx) raises a real consent request per patient/HIP
but had no way to get it APPROVED -- repo/storage evidence showed several
of our own self-raised requests sitting REQUESTED forever, never
GRANTED, because nothing ever told ABDM to auto-approve them. Setting
this SAME auto-approve policy once per patient, before ever raising a
self-view request (see data_flow.py's own ensure_self_view_auto_approve()),
is what's supposed to close that gap -- confirmed only as far as the
mechanics of the real 3-call sequence go; whether it actually causes a
subsequent request to auto-grant is what Aayush's own live test settles.

P11's OWN /cm/... CALL THEN FAILED THREE TIMES LIVE (P12, 2026-09-02):
{"code": "1513", "message": "Invalid HIU ID"}, tried with a facility id
alone, facility id + name, and an internal numeric id looked up from
ABDM's own Gateway (server/auth.py's find_bridge_service_by_id()) -- the
id was independently confirmed genuinely registered/active/isHiu=true
each time, so the id's VALUE was never the problem in any of those three
shapes. Two live-untested possibilities remained open: (a) spec §6.13's
OWN endpoint (/api/hiecm/consent/v3/auto/approve -- what auto_approve()
implemented before P11 rewrote it) might have been right all along, just
never actually tried; (b) /cm/... might be right but wants CLIENT_ID
(the bridge's own identity), not a facility id, for hiu.id. Rather than
guess a fourth combination, auto_approve_v3_hiecm() below adds the §6.13
endpoint back as a SEPARATE, independently-callable function (auto_approve()
itself is untouched) so data_flow.py's own ensure_self_view_auto_approve()
can try an ORDERED sequence across both endpoints and both identity
values and report definitively which (if any) actually works -- see that
function's own docstring for the exact order and why.

RETRY: reads (#4/#5/#9/#10/#11) use the DEFAULT classifier -- side-effect-
free, safe to retry freely, same reasoning as links.py. Actions
(#1/#2/#3/#6/#7/#8) also use the DEFAULT classifier -- none of them
consume a single-use secret the way an OTP does (a resubmitted approve/
deny/revoke on a transient failure is a repeat of the SAME decision, not
a new one), matching this project's own established distinction between
"retrying risks a duplicate real-world side effect" (OTP sends) and
"retrying just resubmits the identical, idempotent-in-intent request"
(every POST in this module). Still real, state-changing calls on ABDM's
side -- tested deliberately live, not blindly, per this chunk's own
verification instructions.
"""

import time
from typing import Any
from uuid import uuid4

import requests
from pydantic import BaseModel

from abdm_core.http import call_with_retry, generate_request_id, generate_timestamp
from abdm_core.observability.flow_logger import log_api_call, log_error, log_phase
from abdm_core.session import get_gateway_token

from aegle_phr.phr.call_log import archive
from aegle_phr.phr.enrollment import AbdmResult
from aegle_phr.settings import Settings

_TIMEOUT_SECONDS = 30


# ---------------------------------------------------------------------------
# Response contracts -- documented, never used to gate. NONE of these are
# confirmed against a live capture; see module banner.
# ---------------------------------------------------------------------------

class ConsentPurpose(BaseModel):
    text: str | None = None
    code: str | None = None
    refUri: str | None = None


class ConsentParty(BaseModel):
    id: str | None = None
    name: str | None = None
    type: str | None = None


class ConsentCareContext(BaseModel):
    patientReference: str | None = None
    careContextReference: str | None = None


class ConsentRequesterIdentifier(BaseModel):
    value: str | None = None
    type: str | None = None
    system: str | None = None


class ConsentRequester(BaseModel):
    name: str | None = None
    identifier: ConsentRequesterIdentifier | None = None


class ConsentPermission(BaseModel):
    accessMode: str | None = None
    dateRange: dict[str, Any] | None = None
    dataEraseAt: str | None = None
    frequency: dict[str, Any] | None = None


class ConsentRequestItem(BaseModel):
    """Spec §6.16's own per-entry shape (Get All Consent Requests) -- identical to §6.17's un-paginated single-request shape."""

    requestId: str | None = None
    purpose: ConsentPurpose | None = None
    patient: ConsentParty | None = None
    hip: ConsentParty | None = None
    hiu: ConsentParty | None = None
    careContexts: list[ConsentCareContext] = []
    requester: ConsentRequester | None = None
    status: str | None = None
    createdAt: str | None = None
    lastUpdated: str | None = None
    hiType: list[str] = []
    permission: ConsentPermission | None = None


class GetAllConsentRequestsResponse(BaseModel):
    """Spec §6.16's own documented shape. UNCONFIRMED against a live capture."""

    size: int | None = None
    limit: int | None = None
    offset: int | None = None
    requests: list[ConsentRequestItem] = []


class ConsentDetail(BaseModel):
    """#9/#10's own nested `consentDetail` -- same shape as ConsentRequestItem plus two extra fields per the spec's own example."""

    requestId: str | None = None
    purpose: ConsentPurpose | None = None
    patient: ConsentParty | None = None
    hip: ConsentParty | None = None
    hiu: ConsentParty | None = None
    careContexts: list[ConsentCareContext] = []
    hiType: list[str] = []
    permission: ConsentPermission | None = None
    schemaVersion: str | None = None
    consentManager: ConsentParty | None = None


class ConsentArtefactItem(BaseModel):
    """#9's own per-entry shape (spec §6.18) -- an array of these. UNCONFIRMED whether #10 (single artefact by ID) is wrapped the same way or returns one bare item -- flagged in get_consent_artefact()'s own docstring, check live."""

    status: str | None = None
    consentDetail: ConsentDetail | None = None
    signature: str | None = None


class GetAllConsentArtefactsResponse(BaseModel):
    """Spec §6.20's own documented shape (Get All Consent Artefacts). UNCONFIRMED against a live capture."""

    size: int | None = None
    limit: int | None = None
    offset: int | None = None
    consentArtefacts: list[ConsentArtefactItem] = []


def _headers(x_auth_token: str, x_cm_id: str) -> dict[str, str]:
    """Identical to links.py's own _headers() -- same host/header family, see module banner."""
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
    """Shared plumbing for all 11 calls -- mirrors links.py's own get_all_linked_records() body, generalized for GET/POST. Never calls raise_for_status(): a 4xx from ABDM (e.g. denying an already-decided request) is an expected, handled outcome, not an exception."""
    started = time.monotonic()

    def attempt() -> requests.Response:
        if method == "GET":
            return requests.get(url, headers=headers, params=params, timeout=_TIMEOUT_SECONDS)
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


# ---------------------------------------------------------------------------
# 1. Auto-approve -- REWRITTEN ENTIRELY (P11, 2026-09-02), REPLACING the
# spec-§6.13-shaped call this used to make. See this module's own banner
# for the full story: spec §6.13's own documented endpoint
# (POST {abdm_hiecm_base_url}/consent/v3/auto/approve) was always flagged
# "UNCONFIRMED against a live capture" -- correctly, because it does not
# match reality. The REAL mechanism, confirmed via a live-captured Postman
# example (ABDM Collection -> Building PHR App -> Setup Subscriptions/
# Setup Auto-approval, not the spec PDF), is a 3-call sequence under a
# DIFFERENT host entirely (settings.abdm_cm_base_url):
#   1. POST {abdm_cm_base_url}/patients/pin           -- create_consent_pin()
#   2. POST {abdm_cm_base_url}/patients/verify-pin    -- verify_consent_pin()
#   3. POST {abdm_cm_base_url}/consents/auto-approve  -- the real policy call
# Root cause this closes: repo/storage evidence (2026-09-02) showed our own
# self-view consent requests getting raised and on-init-acked correctly,
# but never once approved by anyone -- they just sat REQUESTED forever,
# because nothing had ever told ABDM to auto-grant them. This standing
# policy is what makes that happen without a per-request manual approval.
# ---------------------------------------------------------------------------

CONSENT_PIN = "1111"
"""
Fixed sandbox-only dummy Consent PIN -- same spirit as every other dummy
fixture in this project (test practitioners, test patients, ...). No UI
exists to let a patient choose their own; not needed for this test app.
"""


def create_consent_pin(settings: Settings, x_auth_token: str, pin: str = CONSENT_PIN) -> AbdmResult:
    """
    POST {abdm_cm_base_url}/patients/pin -- sets the patient's Consent PIN.
    Confirmed 204 on a real captured example. ONE-TIME per patient: ABDM
    rejects re-setting an already-set PIN, which is the expected steady
    state after the first call for any given patient on any later call --
    auto_approve() below does NOT treat a non-2xx here as fatal, exactly
    because of this (see its own docstring).
    """
    url = f"{settings.abdm_cm_base_url.rstrip('/')}/patients/pin"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-AUTH-TOKEN": x_auth_token,
    }
    log_phase("Setting consent PIN (one-time -- a non-2xx here usually just means it's already set)")
    return _execute("/phr/consent/pin/create", "POST", url, headers, {"pin": pin}, "PHR create consent PIN")


def verify_consent_pin(settings: Settings, x_auth_token: str, pin: str = CONSENT_PIN) -> AbdmResult:
    """
    POST {abdm_cm_base_url}/patients/verify-pin -- on success, returns
    body.temporaryToken, which the real auto-approve call below needs as
    its OWN X-Auth-Token (deliberately NOT the patient's raw session
    token -- see auto_approve()'s own docstring). `scope` is a fixed
    literal, "consent.autoapprove", confirmed via the same captured
    example. requestId is a fresh uuid4 per call, matching every other
    REQUEST-ID-shaped field in this project's own ABDM calls.
    """
    url = f"{settings.abdm_cm_base_url.rstrip('/')}/patients/verify-pin"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-AUTH-TOKEN": x_auth_token,
    }
    payload = {"pin": pin, "requestId": str(uuid4()), "scope": "consent.autoapprove"}
    log_phase("Verifying consent PIN for a temporary auto-approve token")
    return _execute("/phr/consent/pin/verify", "POST", url, headers, payload, "PHR verify consent PIN")


def auto_approve(
    settings: Settings,
    x_auth_token: str,
    hiu_id: str,
    hi_types: list[str],
    purpose_text: str,
    purpose_code: str,
    purpose_ref_uri: str,
    period_from: str,
    period_to: str,
    is_applicable_for_all_hips: bool = True,
    hiu_name: str | None = None,
) -> AbdmResult:
    """
    Sets a STANDING POLICY, not a one-time action: future consent requests
    from this HIU (or all HIPs, per is_applicable_for_all_hips) matching
    these hiTypes/purpose/date-range auto-grant without the patient
    reviewing each one.

    INTERNALLY RUNS ALL THREE REAL CALLS (create-pin, verify-pin, the real
    auto-approve) -- this function's own OUTWARD signature/behavior is
    unchanged from before this pass (same params, same x_auth_token,
    callers/routes need no changes) even though what it does underneath is
    now completely different. create_consent_pin()'s own result is
    deliberately NOT checked for success -- a non-2xx there just means
    this patient already has a PIN, the expected steady state after the
    first call ever made for them, not a reason to stop. verify_consent_pin()
    IS load-bearing: its own temporaryToken is what gets sent as this
    call's X-Auth-Token (case exactly as captured -- different from the
    X-AUTH-TOKEN header every other call in this module uses), NOT
    x_auth_token itself. Body shape (isApplicableForAllHIPs/hiu/
    includedSources/excludedSources) is unchanged from this function's own
    pre-P11 shape -- only the URL, and where the auth header's value comes
    from, were ever wrong.

    Returns the real auto-approve call's own AbdmResult on success. If
    verify_consent_pin() itself fails (no temporaryToken means the real
    call literally cannot be made), returns THAT failed AbdmResult
    instead, so a caller sees exactly where this stopped rather than a
    confusing downstream failure.

    hiu_name: ADDED after a live-confirmed failure (2026-09-02) --
    sending `hiu: {"id": hiu_id}` alone got a 400 back, `{"code": "1513",
    "message": "Invalid HIU ID"}`, even though a separate, read-only
    lookup (server/auth.py's find_services_by_bridge_id(), called
    directly against ABDM's own Gateway) confirmed that EXACT id is
    genuinely registered, active, and typed ["HIP", "HIU"] under our own
    bridge -- so the id itself was never wrong. The one concrete
    difference from the real captured Postman example this module's own
    banner is built on: that example's own payload sent BOTH `hiu.id`
    AND `hiu.name` ("HIU_007"/"Keeladi hospital"), not id alone. Optional
    here (None omits `name` entirely, preserving the exact old payload
    shape for any caller that doesn't have one to hand) so this stays
    backward compatible, but self-view's own caller
    (data_flow.py's ensure_self_view_auto_approve()) always supplies it
    now.
    """
    pin_result = create_consent_pin(settings, x_auth_token)
    if not pin_result.ok:
        log_phase(f"Consent PIN create returned {pin_result.status_code} -- likely already set for this patient, continuing")

    verify_result = verify_consent_pin(settings, x_auth_token)
    temporary_token = verify_result.body.get("temporaryToken") if isinstance(verify_result.body, dict) else None
    if not temporary_token:
        log_error("Consent PIN verify did not return a temporaryToken -- cannot proceed to the real auto-approve call")
        return verify_result

    url = f"{settings.abdm_cm_base_url.rstrip('/')}/consents/auto-approve"
    hiu = {"id": hiu_id, "name": hiu_name} if hiu_name else {"id": hiu_id}
    payload = {
        "isApplicableForAllHIPs": is_applicable_for_all_hips,
        "hiu": hiu,
        "includedSources": [
            {
                "hiTypes": hi_types,
                "purpose": {"text": purpose_text, "code": purpose_code, "refUri": purpose_ref_uri},
                "period": {"from": period_from, "to": period_to},
            }
        ],
        "excludedSources": [],
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_gateway_token()}",
        "X-Auth-Token": temporary_token,
        "x-cm-Id": settings.abdm_x_cm_id,
    }
    log_phase("Setting Consent Auto-Approval policy")
    return _execute("/phr/consent/auto-approve", "POST", url, headers, payload, "PHR consent auto-approve")


def auto_approve_v3_hiecm(
    settings: Settings,
    x_auth_token: str,
    hiu_id: str,
    hi_types: list[str],
    purpose_text: str,
    purpose_code: str,
    purpose_ref_uri: str,
    period_from: str,
    period_to: str,
    is_applicable_for_all_hips: bool = True,
    hiu_name: str | None = None,
) -> AbdmResult:
    """
    P12 -- the OTHER documented shape for Consent Auto-Approval, tried
    alongside (NOT replacing) auto_approve() above, because neither has
    ever been proven to actually work under our own registration and two
    "official-ish" sources disagree about which is right: spec §6.13 and
    this project's own "PHR" Postman collection both point at
    POST {abdm_hiecm_base_url}/consent/v3/auto/approve -- the SAME host/
    header family (Authorization + X-AUTH-TOKEN + X-CM-ID + REQUEST-ID/
    TIMESTAMP, via this module's own _headers()) every other confirmed-
    working call in this file already uses, unlike auto_approve()'s own
    /cm/... host and its PIN-create/verify-pin/temporaryToken dance.
    auto_approve() above matches the PUBLIC ABDM sandbox docs' "Building a
    PHR App" walkthrough instead, and has one real captured success
    example elsewhere -- but has failed three separate times against our
    own registration (facility id alone, facility id + name, an internal
    numeric id) with {"code": "1513", "message": "Invalid HIU ID"}, never
    yet tried with CLIENT_ID instead of a facility id.

    Body shape is IDENTICAL to auto_approve()'s own (isApplicableForAllHIPs/
    hiu/includedSources/excludedSources) -- only the URL, headers, and the
    complete absence of any PIN step differ. See data_flow.py's own
    ensure_self_view_auto_approve() for the ordered sequence this function
    is step 1/2 of.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/consent/v3/auto/approve"
    hiu = {"id": hiu_id, "name": hiu_name} if hiu_name else {"id": hiu_id}
    payload = {
        "isApplicableForAllHIPs": is_applicable_for_all_hips,
        "hiu": hiu,
        "includedSources": [
            {
                "hiTypes": hi_types,
                "purpose": {"text": purpose_text, "code": purpose_code, "refUri": purpose_ref_uri},
                "period": {"from": period_from, "to": period_to},
            }
        ],
        "excludedSources": [],
    }
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase("Setting Consent Auto-Approval policy (§6.13, /api/hiecm/ variant)")
    return _execute("/phr/consent/auto-approve-v3-hiecm", "POST", url, headers, payload, "PHR consent auto-approve (v3 hiecm)")


# ---------------------------------------------------------------------------
# 2/3. Disable / Enable auto-approve  --  spec §6.14/§6.15
# ---------------------------------------------------------------------------

def _set_auto_approve_state(settings: Settings, x_auth_token: str, consent_id: str, enable: bool, route: str, description: str) -> AbdmResult:
    action = "enable" if enable else "disable"
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/consent/v3/auto/approve/{consent_id}/{action}"
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    return _execute(route, "POST", url, headers, {}, description)


def disable_auto_approve(settings: Settings, x_auth_token: str, consent_id: str) -> AbdmResult:
    """No request body. Expected 202 Accepted, no documented response either place. UNCONFIRMED."""
    log_phase(f"Disabling auto-approve policy {consent_id}")
    return _set_auto_approve_state(settings, x_auth_token, consent_id, False, "/phr/consent/auto-approve/disable", "PHR consent auto-approve disable")


def enable_auto_approve(settings: Settings, x_auth_token: str, consent_id: str) -> AbdmResult:
    """No request body. Expected 202 Accepted, no documented response either place. UNCONFIRMED."""
    log_phase(f"Enabling auto-approve policy {consent_id}")
    return _set_auto_approve_state(settings, x_auth_token, consent_id, True, "/phr/consent/auto-approve/enable", "PHR consent auto-approve enable")


# ---------------------------------------------------------------------------
# 4. All consent requests  --  GET /consent/v3/request  --  spec §6.16
# ---------------------------------------------------------------------------

def get_all_consent_requests(settings: Settings, x_auth_token: str, limit: int = 10, offset: int = 0, status: str = "ALL") -> AbdmResult:
    """
    The inbox. `limit`/`offset`/`status` all caller-overridable, defaulting
    to the spec's own example URL (?limit=10&offset=0&status=ALL).
    Response shape: GetAllConsentRequestsResponse -- the spec's own
    documented example, UNCONFIRMED against a live capture.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/consent/v3/request"
    params = {"limit": limit, "offset": offset, "status": status}
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase("Fetching all consent requests")
    return _execute("/phr/consent/requests/get-all", "GET", url, headers, None, "PHR get all consent requests", params=params)


# ---------------------------------------------------------------------------
# 5. Consent request details  --  GET /consent/v3/request/{id}  --  spec §6.17
# ---------------------------------------------------------------------------

def get_consent_request_details(settings: Settings, x_auth_token: str, consent_request_id: str) -> AbdmResult:
    """
    Same per-item shape as one entry of #4's `requests[]`, un-paginated
    (ConsentRequestItem). This is what supplies the data to pre-fill
    Approve (#6) -- see approve_consent_request()'s own docstring and
    this module's banner for the full design judgment call. UNCONFIRMED
    against a live capture.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/consent/v3/request/{consent_request_id}"
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase(f"Fetching consent request details {consent_request_id}")
    return _execute("/phr/consent/requests/get-one", "GET", url, headers, None, "PHR get consent request details")


# ---------------------------------------------------------------------------
# 6. Approve  --  POST /consent/v3/request/{id}/approve  --  Postman ONLY,
#    not in the spec PDF at all -- see module banner.
# ---------------------------------------------------------------------------

def approve_consent_request(settings: Settings, x_auth_token: str, consent_request_id: str, consents: list[dict[str, Any]]) -> AbdmResult:
    """
    NOT IN THE SPEC PDF -- confirmed real via Postman's own saved request
    06 ("Approve"), the sole source for this endpoint's existence, URL,
    and body shape: {"consents": [{"hiTypes", "hip": {"id"}, "careContexts":
    [{"patientReference","careContextReference"}], "permission":
    {"dateRange": {"to","from"}, "frequency": {"unit","value","repeats"},
    "accessMode", "dataEraseAt"}}]}.

    `consents` is taken AS-IS from the caller -- this function does not
    itself decide what's being granted. testui's ConsentScreen.tsx builds
    this list from an actual HIP + care-context picker (sourced from
    Linked Records, spec §9 -- #5's own response never carries a hip/
    careContexts to accept as-is), submitting the request's own hiTypes/
    permission UNCHANGED per HIP but the patient's own picked hip/
    careContexts selection (narrowing which hiTypes to grant per-HIP
    remains a documented nice-to-have, not built here). See this module's
    own banner for the full reasoning.

    Response shape UNCONFIRMED -- no saved Postman example response and
    no spec entry to compare against, since the endpoint isn't in the
    spec at all.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/consent/v3/request/{consent_request_id}/approve"
    payload = {"consents": consents}
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase(f"Approving consent request {consent_request_id}")
    return _execute("/phr/consent/requests/approve", "POST", url, headers, payload, "PHR approve consent request")


# ---------------------------------------------------------------------------
# 7. Deny  --  POST /consent/v3/request/{id}/deny  --  spec §6.21
# ---------------------------------------------------------------------------

def deny_consent_request(settings: Settings, x_auth_token: str, consent_request_id: str, reason: str) -> AbdmResult:
    """Spec's own words: "invoked from the PHR or mobile application." Body: {"reason": "..."}. Response shape UNCONFIRMED."""
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/consent/v3/request/{consent_request_id}/deny"
    payload = {"reason": reason}
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase(f"Denying consent request {consent_request_id}")
    return _execute("/phr/consent/requests/deny", "POST", url, headers, payload, "PHR deny consent request")


# ---------------------------------------------------------------------------
# 8. Revoke  --  POST /consent/v3/revoke  --  spec §6.22
# ---------------------------------------------------------------------------

def revoke_consents(settings: Settings, x_auth_token: str, consent_ids: list[str]) -> AbdmResult:
    """
    Acts on already-GRANTED artefacts, NOT a pending request -- this is
    what "My Active Consents" (#11) offers per-row/multi-select. Body is
    an ARRAY ({"consents": [...]}), so one call can revoke multiple
    artefacts at once. Spec's own words: "from the PHR or mobile
    application." Response shape UNCONFIRMED.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/consent/v3/revoke"
    payload = {"consents": consent_ids}
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase(f"Revoking {len(consent_ids)} consent artefact(s)")
    return _execute("/phr/consent/revoke", "POST", url, headers, payload, "PHR revoke consents")


# ---------------------------------------------------------------------------
# 9. Consent artefact details by request ID  --  GET /consent/v3/artefact/request/{id}  --  spec §6.18
# ---------------------------------------------------------------------------

def get_consent_artefacts_by_request(settings: Settings, x_auth_token: str, consent_request_id: str) -> AbdmResult:
    """
    The granted artefact(s) tied to one request -- a request approved
    against multiple HIPs produces multiple artefacts, hence an ARRAY of
    {"status", "consentDetail": {...}, "signature"}. Response shape is
    the spec's own documented example. UNCONFIRMED against a live capture.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/consent/v3/artefact/request/{consent_request_id}"
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase(f"Fetching consent artefacts for request {consent_request_id}")
    return _execute("/phr/consent/artefacts/get-by-request", "GET", url, headers, None, "PHR get consent artefacts by request")


# ---------------------------------------------------------------------------
# 10. Consent artefact details by artefact ID  --  GET /consent/v3/artefact/{id}  --  spec §6.19
# ---------------------------------------------------------------------------

def get_consent_artefact(settings: Settings, x_auth_token: str, consent_id: str) -> AbdmResult:
    """
    Same per-item shape as #9, but the spec's own example for THIS
    endpoint shows a single object, NOT wrapped in an array -- unlike #9's
    array-of-one-request's-worth-of-artefacts. Whether the real sandbox
    actually differs from #9's wrapping is UNCONFIRMED -- check live,
    don't assume the spec's two examples are both right.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/consent/v3/artefact/{consent_id}"
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase(f"Fetching consent artefact {consent_id}")
    return _execute("/phr/consent/artefacts/get-one", "GET", url, headers, None, "PHR get consent artefact")


# ---------------------------------------------------------------------------
# 11. All consent artefacts  --  GET /consent/v3/artefact  --  spec §6.20
# ---------------------------------------------------------------------------

def get_all_consent_artefacts(settings: Settings, x_auth_token: str, limit: int = 10, offset: int = 0, status: str = "ALL") -> AbdmResult:
    """
    "My Active Consents" -- Revoke (#8) should be reachable from each row
    here. Response shape: GetAllConsentArtefactsResponse -- the spec's
    own documented example, UNCONFIRMED against a live capture.
    """
    url = f"{settings.abdm_hiecm_base_url.rstrip('/')}/consent/v3/artefact"
    params = {"limit": limit, "offset": offset, "status": status}
    headers = _headers(x_auth_token, settings.abdm_x_cm_id)
    log_phase("Fetching all consent artefacts")
    return _execute("/phr/consent/artefacts/get-all", "GET", url, headers, None, "PHR get all consent artefacts", params=params)
