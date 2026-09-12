"""
Data Flow (spec §7): fetching real health-record content for an already-
GRANTED consent. Architecturally different from every other module in
aegle_phr/phr/ -- confirmed directly against §7.3.1-7.3.5, all five of
this section's ABDM endpoints require an X-HIU-ID header and NONE of them
take a patient session token (X-AUTH-TOKEN). The patient's own PHR app
has no HIU registration of its own to call these as -- it cannot make
this call "as itself" the way it can Consent/Links/Provider-Directory.

THE REUSE DECISION (confirmed with Aayush directly, 2026-09-01): the
entity that DOES have HIU capability is already sitting right next to
this project -- repo/server/hiu_consent.py's own docstring calls its
identity "our HIU identifier", and repo/server/hiu_health_information.py
already implements the entire §7 flow (request -> on-request ack -> HIP
data push -> decrypt -> notify) against it, proven live: real decrypted
FHIR content already sits in repo/storage/hiu_health_information.jsonl
from an actual sandbox round trip. This module is a THIN WRAPPER that
imports and calls that existing code at runtime -- it does not
reimplement any part of the ECDH/decrypt pipeline, and it makes NO direct
ABDM calls of its own (so none of CERTIFICATES.md's rules apply here at
all -- there is no certificate/header/host decision for this module to
make).

THE ONE-TIME EXCEPTION TO "NEVER TOUCH repo/", AND ITS EXACT BOUNDARY:
this module READS AND CALLS repo/'s existing functions. It never MODIFIES
any file under repo/. Every import below is lazy (inside the function
body, not at module top level) specifically so aegle_phr keeps working
standalone for every OTHER feature even when repo/ isn't present/mounted
-- only these three functions need repo/ at runtime, and importing lazily
means an ImportError here surfaces as a normal, catchable, per-call
failure with a clear message, not a hard crash the moment this module is
imported at all (which would take down the entire aegle_phr app if it
were ever run standalone -- see aegle_phr/app.py's own "FOR SOLO
DEVELOPMENT ONLY" banner).

SELF-VIEW CONSENT SEPARATION (P9, 2026-09-02) -- WHY request_self_view_consent()
EXISTS, REPLACING AN EARLIER, WRONGER DESIGN: HomeScreen.tsx's own
extractCoveringConsents() used to grab WHATEVER consent artefact was
GRANTED for a linked HIP, regardless of who requested it or why -- PHR
(the patient viewing their own data), HIP (a facility), and HIU (an
entity requesting a patient's data) are three genuinely distinct roles in
ABDM's model, and treating "any granted artefact" as interchangeable with
"the patient's own self-view" blended them: a THIRD PARTY's consent (say,
a doctor's) and the patient's own ability to see their own linked records
could resolve to the exact same artefact, so revoking the doctor's access
could silently break the patient's own "Pull Records" for that facility,
or vice versa. Fixed by giving self-view its OWN dedicated consent,
raised under purpose.code "PATRQT" ("Self Requested", the spec's own real
purpose code) via this function, with HomeScreen.tsx's own
extractCoveringConsents() now filtering strictly on that purpose code --
see that screen's own banner for the full story and the auto-provisioning
flow built on top of this function.

THE WORKING ASSUMPTION THIS RESTS ON, NOT YET PROVEN FOR THIS PROJECT'S
OWN REGISTRATION: Aayush has directly observed, from ABDM's own external
sandbox/reference app, that a self-view ("PATRQT") consent request seems
to auto-grant with no visible patient approval step -- consistent with
one real captured example (an externally-raised PATRQT notify arriving
already "status": "GRANTED" about a second after the corresponding UIL
confirm). The theory: Consent Manager's whole "sits as REQUESTED until
approved" mechanism exists because a THIRD PARTY is asking, and PATRQT is
structurally different -- requester and approver are the same entity.
This has NEVER been confirmed for a PATRQT request raised through THIS
project's own initiate_consent_request() specifically -- every piece of
evidence so far comes from ABDM's own external app, not this one. If it
turns out NOT to auto-grant here, nothing about this function breaks --
it just means the caller (HomeScreen.tsx's own auto-provisioning) falls
back to leaving the request sitting as REQUESTED, approvable through
P8's own picker like any other request. See HomeScreen.tsx's own banner
for exactly how that fallback works and Aayush's own two live tests that
actually settle this.

THE WORKING ASSUMPTION TURNED OUT FALSE -- ROOT CAUSE FOUND AND FIXED
(P11, 2026-09-02): confirmed against real repo/storage evidence, several
self-view requests raised through THIS project's own registration got
their on-init ack correctly but were never approved by anyone, ever --
not auto-granted, not manually decided, just sitting REQUESTED. Not a
registration-type problem, not an architecture problem: ABDM's own
Consent Auto-Approval is a real, genuine standing-policy feature (a
create-pin/verify-pin/set-policy sequence under a DIFFERENT host,
settings.abdm_cm_base_url -- see aegle_phr/phr/consent.py's own rewritten
auto_approve() for the full mechanics) that this project had a manual
test button for but never actually wired into the self-view flow itself.
ensure_self_view_auto_approve() below sets that policy up, scoped to our
own self-view identity, so a request raised AFTER it should auto-grant.
Whether it actually does is what Aayush's own live test settles -- if it
doesn't, the P8 manual-approval fallback (this file's own banner, two
paragraphs up) is still exactly where things land, unchanged.

THE PRECONDITION THAT DETERMINES WHETHER "FETCH MY RECORDS" CAN WORK AT
ALL FOR A GIVEN CONSENT: initiate_health_information_request() internally
calls validate_date_range_against_consent(), which reads the consent
artefact from repo/'s OWN LOCAL CACHE
(hiu_consent_repository.get_hiu_consent(consent_id)) -- populated only
when repo/server/hiu_consent.py's own CLI flow ran its "Consent Fetch"
step for that specific consentId. aegle-phr's own live ConsentScreen
reads consent status straight from ABDM and has NO relationship to this
local cache whatsoever -- a consent showing GRANTED there may still have
no local record here (never raised/fetched via that CLI). A consent that
WAS fetched here and later revoked is now correctly reflected -- repo/'s
own consent_hiu_notify_service.py (fixed 2026-09-02, same day, a
different live bug report) deletes the locally-cached artefact the
moment ABDM's own REVOKED/EXPIRED notify lands, so get_hiu_consent()
below genuinely returns None once that happens, not a stale "GRANTED"
snapshot -- though repo/'s own hiu_health_information.py also now checks
the consent's own stored status directly (ConsentNotActiveError) as a
second, independent layer, for the residual window before that notify
arrives. Checked explicitly here too, with its own clear error message,
BEFORE calling into repo/'s own code, so a missing-locally consent shows
up as a specific, actionable message rather than repo/'s own generic
DateRangeValidationError/ConsentNotActiveError text (which is already
fairly clear on this, but this module's own check runs first and doesn't
depend on that wording staying the same).

CORRELATION CHAIN (mirrors tools/m3_test_suite/flows/health_information_request.py's
own working reference implementation, read in full before writing this):
initiate_health_information_request() -> response.aegle_request_id ->
poll get_pending_health_information_request(request_id) until it carries
a transaction_id -> poll get_hiu_health_information(transaction_id) until
non-None -> render care_contexts. Deliberately NOT porting the CLI's own
wait_for_callback() -- that watches capture files synchronously in a
blocking CLI loop; for a web backend, the frontend just re-calls this
module's own get_health_information_status() on a short interval, since
both repository reads it does are plain, fast, side-effect-free file-
store lookups.

RESPONSE ENVELOPE: all three functions return a plain
{"ok", "status", "body", "error"} dict -- deliberately the SAME shape
_passthrough() builds from an AbdmResult elsewhere in this project, even
though neither function here wraps an AbdmResult (no direct ABDM call is
made) -- this lets the frontend reuse ApiResult<AbdmPassthrough> and the
shared RawBody component unchanged rather than inventing a second
response convention for just this one module.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from abdm_core.http import generate_request_id
from abdm_core.observability.flow_logger import log_error, log_phase

from aegle_phr.phr import consent, subscription
from aegle_phr.phr.subscription_repository import save_new_subscription_request
from aegle_phr.settings import Settings

# Same broad list HomeScreen.tsx's own SELF_VIEW_DEFAULT_HI_TYPES uses for
# the RAISE call's own fallback -- kept in sync deliberately (see
# ensure_self_view_auto_approve()'s own docstring for why the POLICY needs
# to be at least this broad).
_SELF_VIEW_HI_TYPES = [
    "Prescription", "DiagnosticReport", "OPConsultation", "DischargeSummary",
    "ImmunizationRecord", "HealthDocumentRecord", "WellnessRecord", "Invoice",
]


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def request_self_view_consent(
    hi_types: list[str],
    date_range_from: str,
    date_range_to: str,
    patient_abha_address: str,
) -> dict[str, Any]:
    """
    P9 -- self-view consent separation (spec §6). Raises a DEDICATED,
    self-scoped consent request -- purpose.code "PATRQT" ("Self Requested",
    the spec's own real purpose code, confirmed in tools/m3_test_suite/
    common.py's own purpose table) -- by calling repo/server/hiu_consent.py's
    existing initiate_consent_request(). Same lazy-import, ImportError-
    guarded, read-and-call-never-modify pattern as this module's other two
    functions -- see this module's own banner.

    WHY THIS EXISTS: HomeScreen.tsx's own extractCoveringConsents() used to
    grab WHATEVER consent artefact was GRANTED for a HIP, regardless of who
    requested it -- meaning a doctor's own consent (about the doctor's own
    access) and the patient's own self-view could resolve to the exact same
    artefact. Filtering strictly on purpose.code == "PATRQT" (see
    HomeScreen.tsx's own rewritten extractCoveringConsents()) needs an
    artefact that actually HAS that purpose code to filter TO -- this
    function is what raises one.

    hip/careContexts are NOT parameters here: initiate_consent_request()
    already always sends both as JSON null (confirmed in that function's
    own code/docstring) -- ABDM/the patient resolves which HIP(s) this
    covers, whether via the working assumption's own auto-grant (see
    HomeScreen.tsx's own banner) or via manual approval through this
    project's own Approve picker (P8, ConsentScreen.tsx). ONE broad request
    per call, not one per linked facility -- multiple HIPs get resolved
    under this same request, not N separate requests.

    hiu_id: this sandbox has no single separate "PHR's own HIU identity" --
    repo/server/config.py's own HIPS list is the only registered identity
    roster that exists, and repo/'s own M3 CLI already treats a facility's
    hip_id as usable as a hiu_id interchangeably (see hiu_consent.py's own
    CLI flow comment: "HIU ID isn't a separate identity from the facility
    in this sandbox setup"). Reads HIPS[0]["hip_id"] from repo/'s own live
    config at call time (not a hardcoded copy here) so this stays in sync
    if that roster ever changes -- which one specifically is used is not
    load-bearing for a self-view request (same reasoning as the requester
    identifier fields below).

    requester_name/identifier fields: NOT load-bearing for what this
    request can be used for afterward -- repo/server/hiu_health_information.py's
    own initiate_health_information_request() precondition
    (get_hiu_consent(consent_id)) only ever has a row for a consent OUR OWN
    registration itself raised and fetched, so a consent from a different
    app entirely is structurally unusable here regardless of what its
    requester.name says (see HomeScreen.tsx's own banner for the full
    reasoning this rests on). requester_identifier_type/value/system below
    are therefore simple, honest placeholders (this project's own ABHA
    address doubling as the identifier value), not a confirmed ABDM
    convention for a self-requesting PHR app -- flagged as such, not
    presented as researched.

    data_erase_at: computed here (now + 30 days), same convention as
    tools/m3_test_suite/flows/hiu_consent.py's own CLI default -- not a
    caller-supplied parameter, since nothing about self-view needs this to
    vary per call.

    NO REQUESTID IS RETURNED, UNLIKE request_health_information() BELOW --
    checked directly, not assumed: initiate_consent_request() (unlike its
    sibling initiate_health_information_request()) never attaches an
    aegle_request_id to its response, and its own internally-generated
    REQUEST-ID header value isn't exposed any other way either. This
    turns out not to matter for how this function's caller actually
    identifies "the self-view request" afterward: since purpose.code
    "PATRQT" is now used EXCLUSIVELY for self-view (see HomeScreen.tsx's
    own rewritten extractCoveringConsents()), the caller finds it again by
    filtering #4/GetAllConsentRequests for purpose.code == "PATRQT" -- the
    purpose code itself is the identifying signal, not a captured id.

    Returns:
        {"ok": True, "status": 202, "body": {}, "error": None} on success.
        "ok": False with a specific "error" for: repo/ not importable, or
        a non-202 ABDM response.
    """
    try:
        from server.config import HIPS
        from server.hiu_consent import initiate_consent_request
    except ImportError as exc:
        return {
            "ok": False,
            "status": None,
            "body": None,
            "error": (
                f"repo/'s server package isn't importable from this process ({exc}). "
                "Self-view consent only works when aegle_phr is mounted into "
                "repo/server/main.py (the real deployment target)."
            ),
        }

    if not HIPS:
        return {
            "ok": False,
            "status": None,
            "body": None,
            "error": "repo/server/config.py's own HIPS list is empty -- no HIU identity available to raise a self-view request under.",
        }

    hiu_id = HIPS[0]["hip_id"]
    now = datetime.now(timezone.utc)
    data_erase_at = _iso(now + timedelta(days=30))

    try:
        response = initiate_consent_request(
            hiu_id=hiu_id,
            patient_abha_address=patient_abha_address,
            requester_name="Aegle PHR — My Records",
            requester_identifier_type="ABHA-ADDRESS",
            requester_identifier_value=patient_abha_address,
            requester_identifier_system="https://healthid.abdm.gov.in",
            purpose_text="Self Requested",
            purpose_code="PATRQT",
            purpose_ref_uri="www.abdm.gov.in",
            hi_types=hi_types,
            date_range_from=date_range_from,
            date_range_to=date_range_to,
            data_erase_at=data_erase_at,
        )
    except Exception as exc:
        return {"ok": False, "status": None, "body": None, "error": f"initiate_consent_request() failed: {exc}"}

    if response.status_code != 202:
        try:
            response_body = response.json()
        except ValueError:
            response_body = response.text
        return {
            "ok": False,
            "status": response.status_code,
            "body": {"response": response_body},
            "error": f"Unexpected status {response.status_code} (expected 202 Accepted).",
        }

    return {
        "ok": True,
        "status": 202,
        "body": {},
        "error": None,
    }


def ensure_self_view_auto_approve(settings: Settings, x_auth_token: str) -> dict[str, Any]:
    """
    P12 (2026-09-02, EXTENDED 2026-09-03) -- ORDERED, 4-STEP LIVE TEST
    across two competing documented endpoints and two candidate HIU
    identity values, because neither endpoint has ever been proven to
    actually work under our own registration, and P11's own choice
    (/cm/..., a facility id) failed live three separate times with
    {"code": "1513", "message": "Invalid HIU ID"} -- even though that
    exact id was independently confirmed, via a direct read-only Gateway
    lookup, to be genuinely registered and active. Rather than guess a
    fifth payload variant, this tries every (endpoint x identity)
    combination Aayush and this project's own evidence consider
    plausible, IN THIS ORDER (grouped by identity first, so both
    endpoints get a fresh, same-run, directly-comparable try with the
    facility id before either gets tried with the bridge id), stopping at
    the first real 2xx:

      1. consent.auto_approve_v3_hiecm() -- spec §6.13's own documented
         endpoint (/api/hiecm/consent/v3/auto/approve, the SAME header
         family every other confirmed-working call in consent.py uses) --
         with hiu_id = HIPS[0]["hip_id"] (a facility id, the SAME value
         request_self_view_consent() already uses successfully for the
         separate consent/v3/request/init call).
      2. consent.auto_approve() -- P11's own /cm/... 3-call sequence --
         with hiu_id = the SAME facility id. A fresh, same-run data point
         for this exact combination -- prior evidence for it existed, but
         only from an earlier day/session, not alongside the other three.
      3. consent.auto_approve_v3_hiecm() again, with hiu_id = CLIENT_ID
         (server/config.py's own bridge identity, "SBXID_046112" -- ABDM's
         own bridge-services lookup confirms this IS what ABDM itself
         calls the bridge id, not a separate value) instead of a facility
         id -- tests whether THIS endpoint is right but wants the bridge
         id specifically.
      4. consent.auto_approve() again, with hiu_id = CLIENT_ID instead of
         a facility id (the numeric-id lookup theory from an earlier
         attempt is SUPERSEDED and stays removed) -- tests whether /cm/...
         was right all along and every prior facility-id-shaped attempt
         failed purely on the identity VALUE, not the endpoint.

    Each step's own outcome (status + error/body) is logged via
    log_phase()/log_error() as it happens, REGARDLESS of whether a later
    step succeeds -- this run is as much a diagnostic (which single
    combination, if any, ABDM actually accepts) as it is a fix, and
    Aayush needs the exact per-step evidence either way, not just a final
    yes/no.

    hiTypes/period are unchanged from P11: hiTypes are the broadest this
    project uses anywhere for self-view (_SELF_VIEW_HI_TYPES, all 8
    types) -- request_self_view_consent()'s own hiTypes are narrower in
    the common case, so the policy must be a strict superset of anything
    that call could ever request. period is the POLICY's own validity
    window, NOT request_self_view_consent()'s own date_range despite the
    shared name -- CONFIRMED LIVE, a past (or exactly "now") `from` gets
    rejected outright (error 1500); period_from is "now + 10 minutes" to
    absorb latency/clock-skew between us generating the timestamp and
    ABDM actually validating it, period_to stays ~100 years out.

    Meant to be called ONCE per patient per session, before the first
    self-view request is ever raised -- HomeScreen.tsx's own self-view
    effect guards this with a session-scoped ref, not this function.

    Returns {"ok", "status", "body", "error"}. "ok" true only once a real
    2xx lands, "body" carries that step's own response body PLUS which
    step number/endpoint succeeded (or, if all three failed, a summary of
    all three attempts) so a caller/log reader can tell definitively what
    happened. A failure here is NOT meant to block self-view entirely --
    see HomeScreen.tsx's own call site for the P8 manual-approval
    fallback this degrades to instead of hard-failing.
    """
    try:
        from server.config import HIPS, CLIENT_ID
    except ImportError as exc:
        return {
            "ok": False,
            "status": None,
            "body": None,
            "error": (
                f"repo/'s server package isn't importable from this process ({exc}). "
                "Consent Auto-Approval setup only works when aegle_phr is mounted into "
                "repo/server/main.py (the real deployment target)."
            ),
        }

    if not HIPS:
        return {
            "ok": False,
            "status": None,
            "body": None,
            "error": "repo/server/config.py's own HIPS list is empty -- no HIU identity available to set an auto-approve policy under.",
        }

    facility_id = HIPS[0]["hip_id"]
    facility_name = HIPS[0].get("name")
    # 2026-09-03 -- second facility id, to test whether "Invalid HIU ID" /
    # "Duplicate" is specific to HIPS[0] or a pattern across every
    # registered service. None if this bridge only has one HIP registered.
    second_facility_id = HIPS[1]["hip_id"] if len(HIPS) > 1 else None
    second_facility_name = HIPS[1].get("name") if len(HIPS) > 1 else None

    now = datetime.now(timezone.utc)
    period_from = _iso(now + timedelta(minutes=10))
    period_to = _iso(now + timedelta(days=36500))

    common_kwargs = {
        "settings": settings,
        "x_auth_token": x_auth_token,
        "hi_types": _SELF_VIEW_HI_TYPES,
        "purpose_text": "Self Requested",
        "purpose_code": "PATRQT",
        "purpose_ref_uri": "www.abdm.gov.in",
        "period_from": period_from,
        "period_to": period_to,
    }

    attempts: list[dict[str, Any]] = []

    def _record(step: int, label: str, result) -> bool:
        attempts.append({"step": step, "label": label, "status": result.status_code, "body": result.body, "error": result.error})
        if result.ok:
            log_phase(f"Consent Auto-Approval step {step} ({label}) SUCCEEDED: status={result.status_code}")
        else:
            log_error(f"Consent Auto-Approval step {step} ({label}) failed: status={result.status_code} body={result.body} error={result.error}")
        return result.ok

    # ORDER (2026-09-03, extended after a live gap was found): grouped by
    # IDENTITY first, then endpoint -- both endpoints tried with the
    # facility id, THEN both tried with the bridge id (CLIENT_ID) -- so
    # ONE run gives a complete, same-session, directly-comparable 4-way
    # picture instead of stopping at 3 combinations and leaving one
    # (facility id on /cm/) untested in a fresh run. Earlier live evidence
    # for that exact combination existed but was from a prior day/session,
    # not from the same run as the other three -- not good enough for a
    # clean comparison.
    log_phase(f"Consent Auto-Approval -- step 1/4: /api/hiecm/consent/v3/auto/approve, hiu_id=facility id ({facility_id})")
    step1 = consent.auto_approve_v3_hiecm(hiu_id=facility_id, hiu_name=facility_name, **common_kwargs)
    if _record(1, f"/api/hiecm/, facility id {facility_id}", step1):
        return {"ok": True, "status": step1.status_code, "body": {"succeededStep": 1, "response": step1.body}, "error": None}

    log_phase(f"Consent Auto-Approval -- step 2/4: /cm/consents/auto-approve, hiu_id=facility id ({facility_id})")
    step2 = consent.auto_approve(hiu_id=facility_id, hiu_name=facility_name, **common_kwargs)
    if _record(2, f"/cm/, facility id {facility_id}", step2):
        return {"ok": True, "status": step2.status_code, "body": {"succeededStep": 2, "response": step2.body}, "error": None}

    log_phase(f"Consent Auto-Approval -- step 3/4: /api/hiecm/consent/v3/auto/approve, hiu_id=CLIENT_ID / bridge id ({CLIENT_ID})")
    step3 = consent.auto_approve_v3_hiecm(hiu_id=CLIENT_ID, hiu_name=None, **common_kwargs)
    if _record(3, f"/api/hiecm/, CLIENT_ID/bridge id {CLIENT_ID}", step3):
        return {"ok": True, "status": step3.status_code, "body": {"succeededStep": 3, "response": step3.body}, "error": None}

    log_phase(f"Consent Auto-Approval -- step 4/4: /cm/consents/auto-approve, hiu_id=CLIENT_ID / bridge id ({CLIENT_ID})")
    step4 = consent.auto_approve(hiu_id=CLIENT_ID, hiu_name=None, **common_kwargs)
    if _record(4, f"/cm/, CLIENT_ID/bridge id {CLIENT_ID}", step4):
        return {"ok": True, "status": step4.status_code, "body": {"succeededStep": 4, "response": step4.body}, "error": None}

    # 2026-09-03 -- steps 5/6: a SECOND, DIFFERENT facility id (still not
    # the one request_self_view_consent() actually uses -- these two are
    # diagnostic only, to find out whether "Invalid HIU ID"/"Duplicate" is
    # specific to HIPS[0] or a pattern across every registered service).
    # Skipped cleanly if this bridge only has one HIP registered.
    if second_facility_id is not None:
        log_phase(f"Consent Auto-Approval -- step 5/6: /api/hiecm/consent/v3/auto/approve, hiu_id=second facility id ({second_facility_id})")
        step5 = consent.auto_approve_v3_hiecm(hiu_id=second_facility_id, hiu_name=second_facility_name, **common_kwargs)
        if _record(5, f"/api/hiecm/, second facility id {second_facility_id}", step5):
            return {"ok": True, "status": step5.status_code, "body": {"succeededStep": 5, "response": step5.body}, "error": None}

        log_phase(f"Consent Auto-Approval -- step 6/6: /cm/consents/auto-approve, hiu_id=second facility id ({second_facility_id})")
        step6 = consent.auto_approve(hiu_id=second_facility_id, hiu_name=second_facility_name, **common_kwargs)
        if _record(6, f"/cm/, second facility id {second_facility_id}", step6):
            return {"ok": True, "status": step6.status_code, "body": {"succeededStep": 6, "response": step6.body}, "error": None}

    log_error(f"Consent Auto-Approval -- ALL {len(attempts)} STEPS FAILED: {attempts}")
    return {
        "ok": False,
        "status": None,
        "body": {"attempts": attempts},
        "error": f"All {len(attempts)} Consent Auto-Approval attempts failed -- see body.attempts for each step's exact status/error.",
    }


def ensure_self_subscription(settings: Settings, patient_abha_address: str) -> dict[str, Any]:
    """
    P13 -- mirrors ensure_self_view_auto_approve()'s own pattern for the
    OTHER auto-approve-shaped case spec §8.1 describes: "Subscription will
    get auto approve for health locker for all HIPs and for all HI types."
    Calls 8.3.2 (subscription.initiate_subscription_request()) with
    hiu.id = CLIENT_ID (this project's own established self-service
    identity-reuse convention, confirmed for consent auto-approve and
    self-view raise alike -- see request_self_view_consent()'s own
    docstring), patient.id = the current patient, categories=["LINK","DATA"]
    (both, per 8.1's own description of what auto-approve covers), no
    `hips` (omitted -- covers every HIP, matching 8.1's "for all HIPs").

    UNLIKE ensure_self_view_auto_approve(), THIS CALL NEEDS NO
    X-AUTH-TOKEN AT ALL -- confirmed via the real Postman collection's own
    saved "01 Subscription Request Init" request, which carries only
    REQUEST-ID/TIMESTAMP/X-CM-ID, no patient session token (see
    subscription.py's own _requester_headers() docstring for the full
    reasoning: this is an HIU/locker action ABOUT a patient, structurally
    the same shape as consent-init, not a patient-session-authenticated
    call). So this function's own signature takes no x_auth_token either.

    Persists a row via subscription_repository.save_new_subscription_request()
    BEFORE the call (same reservation order as repo/server/hiu_consent.py's
    own initiate_consent_request()), keyed by a request_id generated HERE
    (not inside subscription.py) so it's known before the call completes
    -- this is what lets aegle_phr/callbacks/subscription_services.py's
    handle_subscription_on_init() correlate the eventual 8.3.3 callback
    back to this exact attempt.

    Meant to be called ONCE per patient per session, same cadence/call
    site as ensure_self_view_auto_approve() -- see HomeScreen.tsx's own
    login effect, where both are fired together so the two self-service
    policies (consent auto-approve, subscription) get set up in the same
    pass. A failure here is NOT meant to block anything else -- self-view/
    Pull Records must keep working regardless of whether subscription
    setup succeeds; this is a best-effort background policy-set, same as
    its consent-auto-approve sibling.

    Returns {"ok", "status", "body", "error"} -- "ok" true only on a real
    2xx from the init call itself (this does NOT wait for the 8.3.3
    callback/auto-grant to land -- that happens asynchronously, tracked in
    subscription_request, visible via the Subscriptions UI once it does).
    """
    try:
        from server.config import CLIENT_ID
    except ImportError as exc:
        return {
            "ok": False,
            "status": None,
            "body": None,
            "error": (
                f"repo/'s server package isn't importable from this process ({exc}). "
                "Self-subscription only works when aegle_phr is mounted into "
                "repo/server/main.py (the real deployment target)."
            ),
        }

    now = datetime.now(timezone.utc)
    period_from = _iso(now + timedelta(minutes=10))
    period_to = _iso(now + timedelta(days=36500))
    request_id = generate_request_id()

    save_new_subscription_request(
        request_id=request_id,
        patient_id=patient_abha_address,
        hiu_id=CLIENT_ID,
        detail={
            "patient": {"id": patient_abha_address},
            "hiu": {"id": CLIENT_ID},
            "categories": ["LINK", "DATA"],
            "period": {"from": period_from, "to": period_to},
        },
    )

    result = subscription.initiate_subscription_request(
        settings,
        patient_id=patient_abha_address,
        hiu_id=CLIENT_ID,
        categories=["LINK", "DATA"],
        period_from=period_from,
        period_to=period_to,
        request_id=request_id,
    )

    if not result.ok:
        log_error(f"Self-subscription init failed for patient={patient_abha_address}: status={result.status_code} body={result.body} error={result.error}")
        return {"ok": False, "status": result.status_code, "body": result.body, "error": result.error or f"Unexpected status {result.status_code} initiating self-subscription."}

    log_phase(f"Self-subscription initiated for patient={patient_abha_address} (requestId={request_id}) -- awaiting on-init callback")
    return {"ok": True, "status": result.status_code, "body": {"requestId": request_id}, "error": None}


def discover_self_view_consents(settings: Settings, x_auth_token: str) -> dict[str, Any]:
    """
    P13 (2026-09-03) -- finds self-view consents ABDM has ALREADY granted
    on its own, without ever going through this project's own auto-
    approve mechanism (ensure_self_view_auto_approve() above) or even a
    request this project raised.

    THE GAP THIS CLOSES: while chasing why P11/P12's own auto-approve
    policy never took effect, a live check of #9 (get_all_consent_artefacts())
    turned up 7 already-GRANTED PATRQT artefacts for a real patient,
    createdAt dates going back to 2026-07-29 -- weeks before this
    project's own auto-approve investigation started, and none raised
    under this project's own registration (requester.name is literally
    "SELF", not this project's HIU identity). Their hiu.id is "sbx_001",
    a value this project has NEVER sent in any auto-approve/request call.
    Conclusion, confirmed live the same day (manual test, not yet wired
    up here): ABDM's sandbox appears to auto-grant self-view natively,
    independent of anything this project does, likely whenever a HIP
    links a care context for that patient. See this project's own
    conversation history for the live proof -- a real FHIR Prescription
    bundle was successfully requested and decrypted using one of these
    artefacts.

    WHY THIS ISN'T USABLE ON ITS OWN: repo/'s own hiu_consent_repository
    (populated by consent_hiu_notify_service.py whenever ABDM tells OUR
    bridge a consent was granted) has ZERO record of any of these seven --
    confirmed by direct lookup. ABDM's notify callback is HIU-directed;
    "sbx_001" isn't a HIU identity this bridge is registered as, so it
    almost certainly never gets sent to us. Without a local record,
    repo/server/hiu_health_information.py's own initiate_health_information_request()
    refuses to touch a consent (see ConsentNotActiveError) -- these
    artefacts sit permanently invisible to this project's own Data Flow
    functions until something tells repo/ about them another way.

    THE FIRST FIX ATTEMPT DIDN'T WORK EITHER -- CONFIRMED LIVE, SAME DAY:
    this originally called trigger_consent_fetch() (right below) for each
    discovered artefact, reusing repo/server/hiu_consent.py's real
    fetch_consent() -- the same call ABDM's own notify callback would
    trigger automatically, so the local record would land the PROPER way
    (via ABDM's own on-fetch callback), not a hand-written one. Checked
    directly against storage/api_capture/server_2026-09-03.jsonl: every
    one of 59 real fetch_consent() calls for these sbx_001-owned
    consents got a genuine 202 Accepted from ABDM -- and NOT ONE ever
    received the on-fetch callback that's supposed to follow. Exactly the
    same structural gap as initiate_health_information_request()'s own
    missing on-request ack (see health_information_hiu_push_service.py's
    own docstring for that one): ABDM accepts the synchronous request,
    but has nowhere confirmed to deliver the async response, because we
    were never registered as HIU "sbx_001". Waiting longer doesn't help --
    the callback isn't late, it structurally never arrives.

    THE ACTUAL FIX: we don't need that callback at all. #9's own response
    (queried below) already carries the full consentDetail + signature +
    status -- the EXACT payload the on-fetch callback would have
    delivered, since it's the same artefact, just fetched from the
    patient's own authenticated session instead of relayed back to the
    HIU async. So each newly-discovered artefact is saved directly via
    save_hiu_consent(), using the data already in hand -- skipping the
    trigger-and-wait dance for a callback that's now confirmed to never
    come for this identity. trigger_consent_fetch() itself is untouched
    below (still correct for a consent OUR OWN registration actually
    raised, where the notify/on-fetch chain does work -- see its own
    docstring) -- this function just no longer routes through it.

    Meant to be called once per patient per session, same cadence as
    ensure_self_view_auto_approve() -- cheap to call repeatedly (the
    already-known check makes every artefact but the first-ever-seen one
    a no-op).

    Returns {"ok", "status", "body", "error"}. "ok" is True once the
    artefact list was successfully retrieved (regardless of whether any
    individual save failed -- those are reported per-item in body, not
    treated as an overall failure, since one bad artefact shouldn't hide
    the others). body: {"totalSelfViewGranted": int, "alreadyKnown":
    [consentId, ...], "registered": [consentId, ...], "failed":
    [{"consentId", "error"}, ...]}. "registered" means the local record
    was written synchronously, in this same call -- unlike the old
    "fetchTriggered" name, there is no further async step to wait on.
    """
    try:
        from server.callbacks.repository.hiu_consent_repository import get_hiu_consent, save_hiu_consent
    except ImportError as exc:
        return {
            "ok": False,
            "status": None,
            "body": None,
            "error": (
                f"repo/'s server package isn't importable from this process ({exc}). "
                "Self-view discovery only works when aegle_phr is mounted into "
                "repo/server/main.py (the real deployment target)."
            ),
        }

    result = consent.get_all_consent_artefacts(settings, x_auth_token, limit=100, status="GRANTED")

    if not result.ok:
        return {
            "ok": False,
            "status": result.status_code,
            "body": result.body,
            "error": result.error or f"Unexpected status {result.status_code} listing consent artefacts.",
        }

    artefacts = (result.body or {}).get("consentArtefacts") or []
    self_view_artefacts = [
        art for art in artefacts
        if ((art.get("consentDetail") or {}).get("purpose") or {}).get("code") == "PATRQT"
    ]

    already_known: list[str] = []
    registered: list[str] = []
    failed: list[dict[str, Any]] = []

    for art in self_view_artefacts:
        detail = art.get("consentDetail") or {}
        consent_id = detail.get("consentId")
        hiu_id = (detail.get("hiu") or {}).get("id")
        status = art.get("status")
        signature = art.get("signature")

        if not consent_id or not hiu_id:
            log_error(f"Self-view artefact missing consentId/hiu.id -- skipping: {detail}")
            continue

        if get_hiu_consent(consent_id) is not None:
            already_known.append(consent_id)
            continue

        try:
            save_hiu_consent(consent_id, {"status": status, "consent_detail": detail, "signature": signature})
        except Exception as exc:
            failed.append({"consentId": consent_id, "error": str(exc)})
            log_error(f"Failed to locally register discovered self-view consent {consent_id}: {exc}")
            continue

        log_phase(f"Registered a native self-view grant ({consent_id}, hiu={hiu_id}) -- usable by Pull Records now")
        registered.append(consent_id)

    return {
        "ok": True,
        "status": 200,
        "body": {
            "totalSelfViewGranted": len(self_view_artefacts),
            "alreadyKnown": already_known,
            "registered": registered,
            "failed": failed,
        },
        "error": None,
    }


def trigger_consent_fetch(consent_id: str, hiu_id: str) -> dict[str, Any]:
    """
    P12 (2026-09-02) -- explicitly calls repo/server/hiu_consent.py's own
    fetch_consent(hiu_id, consent_id), the SAME function
    consent_hiu_notify_service.py normally calls automatically when
    ABDM's own consent-notify callback tells the HIU a request was
    GRANTED.

    WHY THIS EXISTS -- A REAL GAP FOUND LIVE, NOT ANTICIPATED BY P9/P10/
    P11: those three passes all assumed that once a PATRQT self-view
    request becomes GRANTED, the SAME notify -> fetch_consent() ->
    on-fetch chain that demonstrably works for third-party (CAREMGT)
    requests would also fire for it -- populating repo/'s own
    hiu_consent_repository automatically, no different from any other
    consent. Confirmed FALSE for every self-view request raised so far
    (2026-09-02, Pooja Rameshkumar's account): repo/storage/api_capture/
    m3_*.jsonl shows all 6 of our own raised PATRQT requests got their
    on-init ack from ABDM correctly (consent_hiu_on_init, ~0.3-0.6s after
    each raise) -- but NOT ONE of them was ever followed by a
    consent_hiu_notify callback, the entire rest of the day, even though
    consent_hiu_notify callbacks for OTHER (CAREMGT) requests earlier the
    same day worked completely normally. repo/storage/hiu_consents.jsonl
    has zero entries for this patient as a direct result -- fetch_consent()
    had structurally never been called for any of them. The most likely
    explanation: ABDM's own notify webhook is HIU-directed by design (its
    whole job is telling a THIRD PARTY what a patient decided) -- a
    PATRQT request, where the "HIU" and the patient's own decision are
    the same actor, may simply never trigger it in ABDM's real sandbox
    implementation. This has NOT been proven as ABDM's documented
    behavior -- it is what the evidence above shows happening, not a
    confirmed spec fact.

    THE FIX THIS ENABLES: HomeScreen.tsx's own #4-polling already tells
    us the moment our own PATRQT request becomes GRANTED, independent of
    any callback (it's a direct patient-session query against ABDM's CM).
    Once that's known, the frontend fetches #9 to learn the real granted
    consentId, then calls this function directly -- triggering the exact
    same fetch_consent() step the (apparently silent, for this one case)
    notify callback would otherwise have triggered. The DOWNSTREAM half
    of the chain (fetch_consent()'s own on-fetch callback actually
    writing to hiu_consent_repository) is unchanged and already proven
    working -- only the TRIGGER is being supplied a different way here,
    not reimplemented.

    Args:
        consent_id: The GRANTED consent artefact's own id (same field as
            request_health_information()'s own consent_id param).
        hiu_id: Our HIU identifier for this consent (consentDetail.hiu.id
            from the same artefact).

    Returns:
        {"ok": True, "status": 202, "body": {}, "error": None} on a 202
        Accepted ack (the real detail still arrives later, async, via the
        on-fetch callback -- this function does not itself wait for that;
        see HomeScreen.tsx's own retry loop for the caller-side wait).
        "ok": False for: repo/ not importable, or a non-202 response.
    """
    try:
        from server.hiu_consent import fetch_consent
    except ImportError as exc:
        return {
            "ok": False,
            "status": None,
            "body": None,
            "error": f"repo/'s server package isn't importable from this process ({exc}).",
        }

    try:
        response = fetch_consent(hiu_id=hiu_id, consent_id=consent_id)
    except Exception as exc:
        return {"ok": False, "status": None, "body": None, "error": f"fetch_consent() failed: {exc}"}

    if response.status_code != 202:
        try:
            response_body = response.json()
        except ValueError:
            response_body = response.text
        return {
            "ok": False,
            "status": response.status_code,
            "body": {"response": response_body},
            "error": f"Unexpected status {response.status_code} (expected 202 Accepted).",
        }

    return {"ok": True, "status": 202, "body": {}, "error": None}


def request_health_information(
    consent_id: str,
    hip_id: str,
    hiu_id: str,
    date_range_from: str,
    date_range_to: str,
) -> dict[str, Any]:
    """
    Kicks off a Health Information Request (spec §7.3.1) for an already-
    GRANTED consent, by calling repo/server/hiu_health_information.py's
    own initiate_health_information_request() -- see this module's own
    banner for the full precondition/reuse story.

    Args:
        consent_id: The GRANTED consent artefact's own ABDM id --
            consentDetail.consentId, NOT consentDetail.requestId (see
            ConsentScreen.tsx's own updated extraction, corrected this
            same chunk after cross-referencing repo/server/callbacks/
            services/consent_hiu_on_fetch_service.py's own confirmed
            real inbound shape).
        hip_id: consentDetail.hip.id from the same artefact.
        hiu_id: consentDetail.hiu.id from the same artefact -- this
            project's own HIU identity falls out of the consent artefact
            itself (every consent repo/'s own hiu_consent.py CLI raised
            was requested BY this project's own HIU registration, so its
            own hiu.id field already IS "our" identifier -- no separate
            constant to hardcode here).
        date_range_from / date_range_to: ISO 8601, must fall within the
            consent's own approved permission.dateRange.

    Returns:
        {"ok": True, "status": 202, "body": {"requestId": ...}, "error": None}
        on success. "ok": False with a specific "error" message for: repo/
        not importable from this process, no local consent record, an
        out-of-range date, or a non-202 ABDM response.

        The "no local consent record" case ALSO carries a top-level
        "reasonCode": "consent_not_in_local_cache" (P10, 2026-09-02) --
        added specifically so HomeScreen.tsx's own self-view auto-
        provisioning can detect this ONE case programmatically (to mark a
        consentId as known-unusable and stop trusting it as "coverage")
        without string-matching the human-readable "error" text, which is
        free to reword later. Every other error case here has no
        reasonCode (None) -- this is not a general error-taxonomy field,
        just the one case a caller currently needs to branch on.
    """
    try:
        from server.callbacks.repository.hiu_consent_repository import get_hiu_consent
        from server.hiu_health_information import (
            DateRangeValidationError,
            initiate_health_information_request,
        )
    except ImportError as exc:
        return {
            "ok": False,
            "status": None,
            "body": None,
            "error": (
                f"repo/'s server package isn't importable from this process ({exc}). "
                "Data Flow only works when aegle_phr is mounted into repo/server/main.py "
                "(the real deployment target) -- not when run standalone via "
                "aegle_phr.app:create_app (dev-only)."
            ),
        }

    if get_hiu_consent(consent_id) is None:
        return {
            "ok": False,
            "status": None,
            "body": None,
            "error": (
                f"No local record of consent {consent_id!r} in repo/'s own consent cache. "
                "Was this consent raised AND fetched via repo/server/hiu_consent.py's own "
                "CLI flow ('Consent Fetch' step)? aegle-phr's own live Consent Manager reads "
                "straight from ABDM and never populates repo/'s local cache, so a consent "
                "showing GRANTED there may still be unusable here."
            ),
            # P10 -- machine-checkable alongside the prose above. Confirmed
            # live, 2026-09-02: exactly this case fires for a GENUINE,
            # currently-GRANTED consent that a DIFFERENT app/registration
            # raised (e.g. ABDM's own external sandbox app self-granting
            # itself PATRQT access on the same HIP) -- not a data quality
            # problem, a structural one (this consent will NEVER become
            # locally fetchable, no matter how long a caller waits or
            # retries). See HomeScreen.tsx's own P10 section for the one
            # caller that checks this field today.
            "reasonCode": "consent_not_in_local_cache",
        }

    try:
        response = initiate_health_information_request(
            hiu_id=hiu_id,
            consent_id=consent_id,
            hip_id=hip_id,
            date_range_from=date_range_from,
            date_range_to=date_range_to,
        )
    except DateRangeValidationError as exc:
        return {"ok": False, "status": None, "body": None, "error": str(exc)}

    request_id = getattr(response, "aegle_request_id", None)

    if response.status_code != 202:
        try:
            response_body = response.json()
        except ValueError:
            response_body = response.text
        return {
            "ok": False,
            "status": response.status_code,
            "body": {"requestId": request_id, "response": response_body},
            "error": f"Unexpected status {response.status_code} (expected 202 Accepted).",
        }

    return {
        "ok": True,
        "status": 202,
        "body": {"requestId": request_id},
        "error": None,
    }


def get_health_information_status(request_id: str) -> dict[str, Any]:
    """
    One-call poll of the correlation chain described in this module's own
    banner -- looks up the pending session by our own request_id, then
    the stored health information if a transaction_id has been linked.

    Returns a {"ok", "status", "body", "error"} envelope whose `body`,
    on success, is one of:
        {"phase": "pending", "transactionId": None, "careContexts": None}
        {"phase": "transaction_assigned", "transactionId": "...", "careContexts": None}
        {"phase": "complete", "transactionId": "...", "careContexts": {...}}
    "complete" is only returned once the LAST page of a (possibly multi-
    page, multi-care-context) transfer has actually arrived -- see the
    page_number/page_count check below for why an earlier version of this
    function got that wrong. Until then this reports "transaction_assigned"
    (the same phase used before ANY page has arrived), same as any other
    still-in-flight transfer -- callers can't currently distinguish
    "nothing has arrived yet" from "some pages have, more are coming," but
    both cases are, correctly, "keep polling," not "done."
    "ok": False (with "error" set) only when repo/ isn't importable, or
    request_id has no pending session at all (never initiated from this
    process, or repo/'s own pending-session store has since been
    cleared) -- NOT when the transfer is merely still in progress, which
    is a normal, expected intermediate state, not a failure.
    """
    try:
        from server.callbacks.repository.hiu_health_information_repository import (
            get_hiu_health_information,
        )
        from server.callbacks.repository.pending_health_information_request_repository import (
            get_pending_health_information_request,
        )
    except ImportError as exc:
        return {
            "ok": False,
            "status": None,
            "body": None,
            "error": f"repo/'s server package isn't importable from this process ({exc}).",
        }

    pending = get_pending_health_information_request(request_id)
    if pending is None:
        return {
            "ok": False,
            "status": None,
            "body": None,
            "error": (
                f"No pending health information request found for requestId={request_id!r} -- "
                "either it was never initiated from this process, or repo/'s own pending-"
                "session store has since been cleared."
            ),
        }

    transaction_id = pending.get("transaction_id")
    if transaction_id is None:
        return {
            "ok": True,
            "status": 200,
            "body": {"phase": "pending", "transactionId": None, "careContexts": None},
            "error": None,
        }

    stored = get_hiu_health_information(transaction_id)
    if stored is None:
        return {
            "ok": True,
            "status": 200,
            "body": {"phase": "transaction_assigned", "transactionId": transaction_id, "careContexts": None},
            "error": None,
        }

    # LAST-PAGE CHECK ADDED (2026-09-05, real bug found live): a multi-
    # care-context transfer arrives as SEVERAL pages (health_information_
    # hiu_push_service.py's own _push_and_notify() mirror -- one page per
    # care context), and save_hiu_health_information() overwrites this
    # transaction's own stored record on EVERY page as they arrive one by
    # one, not just once at the end. This function used to treat "a
    # stored record exists at all" as "complete" -- true the instant the
    # FIRST page landed, long before the rest. The frontend's own
    # pollStatus() (HomeScreen.tsx) stops polling the moment it sees a
    # non-null careContexts result, so it locked in whatever partial
    # subset had arrived by that first poll and never came back for the
    # remaining pages -- even though they arrived moments later and are
    # sitting in this exact repository, fully merged, right now (confirmed
    # live 2026-09-05: a transaction covering 4 MS Hospital care contexts
    # had all 4 stored as "OK" by its own final page, page_number=3/
    # page_count=4, yet the app only ever showed however many had arrived
    # by the time it first polled -- 1, then 2 across separate attempts,
    # never all 4). tools/m3_test_suite/flows/health_information_request.py
    # (the reference CLI implementation this module's own banner says to
    # mirror) already gets this right -- its own _is_our_last_push()
    # match_fn waits specifically for `page_number >= page_count - 1`
    # before ever calling get_hiu_health_information() -- this was simply
    # never ported here. Missing page_number/page_count (a single-page
    # transfer, or an older/different-shaped stored record) is treated as
    # already complete, same as the CLI's own fallback, so this doesn't
    # regress the common single-page case.
    page_number = stored.get("page_number")
    page_count = stored.get("page_count")
    if page_number is not None and page_count is not None and page_number < page_count - 1:
        return {
            "ok": True,
            "status": 200,
            "body": {"phase": "transaction_assigned", "transactionId": transaction_id, "careContexts": None},
            "error": None,
        }

    return {
        "ok": True,
        "status": 200,
        "body": {"phase": "complete", "transactionId": transaction_id, "careContexts": stored.get("care_contexts") or {}},
        "error": None,
    }
