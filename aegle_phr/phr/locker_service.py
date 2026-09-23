"""
Health Locker automation (P19) -- the only path by which a patient's own
records reach this app.

THE FLOW, end to end:

    patient opts in once
      -> Setup Locker (8.3.18) creates, in ONE call, the locker's already-
         GRANTED subscription AND its consent auto-approval policy
      -> ABDM sends the locker LINK/DATA alerts (8.3.11)
      -> for each alert the locker raises a consent AS THE LOCKER, which
         the auto-approval policy grants without troubling the patient
      -> repo/'s existing consent chain fetches the artefact, and the
         locker-scoped auto-trigger pulls the data
      -> the records are stored and shown to the patient

This replaces the self-view / self-subscription machinery P9-P13 built
(request_self_view_consent, ensure_self_view_auto_approve,
ensure_self_subscription, discover_self_view_consents). Those are gone --
see CC_PROMPT_P19 section 5. Nothing here reads, imports or reuses a
consent raised by any other app or registration.

WHAT "OUR LOCKER" MEANS, AND WHY IT IS CHECKED EVERY TIME: a patient can
hold subscriptions belonging to OTHER apps -- confirmed live, e.g. ABDM's
own sandbox PHR app sbx_001 ("Sanbox Test Hospital") holds a granted
PATRQT subscription for poojaanchaliya@sbx. Those must never satisfy a
"do we have a subscription?" check and must never be acted on. Every
lookup here therefore filters on hiu.id / requester.id == our own locker
id, never on purpose, status or requesterType alone.

TWO LIVE-CONFIRMED DATA QUIRKS this module defends against (2026-09-22):
  - Status casing differs per endpoint: 8.3.17 returns "Granted" where
    8.3.14 and 8.3.15 return "GRANTED" for the very same subscription.
    Every comparison here is case-insensitive.
  - requester.type differs per endpoint for the same subscription:
    "HEALTH_LOCKER" in 8.3.17, "PATIENT" in 8.3.14. Never used as a
    discriminator.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from abdm_core.observability.flow_logger import log_error, log_phase

from aegle_phr.phr import hiu_client
from aegle_phr.phr import locker_hiu_repository as hiu_repo
from aegle_phr.phr import locker_repository as repo
from aegle_phr.phr import subscription
from aegle_phr.settings import Settings

# Statuses that mean "this subscription is usable right now". Compared
# case-insensitively -- see this module's own banner.
_USABLE_STATUSES = {"granted", "active"}

# Statuses that mean the patient (or ABDM) ended it. A subscription in one
# of these is NOT silently recreated -- the patient is asked again.
_ENDED_STATUSES = {"revoked", "expired", "denied"}


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_ours(entry: Any, locker_id: str) -> bool:
    """
    True only when this subscription belongs to OUR locker.

    Checks hiu.id and requester.id (different endpoints use different
    field names for the same thing) and nothing else -- deliberately NOT
    purpose, status or requesterType, any of which another app's
    subscription can also match. See this module's own banner.
    """
    if not isinstance(entry, dict) or not locker_id:
        return False
    for key in ("hiu", "requester"):
        holder = entry.get(key)
        if isinstance(holder, dict) and holder.get("id") == locker_id:
            return True
    return entry.get("lockerId") == locker_id


def _status_of(entry: dict[str, Any]) -> str:
    return str(entry.get("status") or "").strip().lower()


def hi_types_from_contexts(contexts: Any) -> list[str]:
    """
    The HI types named by an 8.3.11 alert's own contexts[].

    UNDOCUMENTED SHAPE, FOUND LIVE 2026-09-23. Spec 8.3.11's example shows
    one HI type per context entry ("hiType": "Prescription"), so the
    obvious reading is that the field holds a single value. It does not:
    a real alert for a care context carrying three HI types arrived as a
    SINGLE entry with

        "hiType": "Prescription,Invoice,OPConsultation"

    -- one comma-joined string. Passing that through verbatim produced a
    consent request whose hiTypes was ["Prescription,Invoice,OPConsultation"],
    i.e. one HI type that does not exist. ABDM still answered 202, so
    nothing looked wrong at the call site; the consent simply never became
    usable and the alert sat at CONSENT_REQUESTED.

    Splitting on commas here handles both shapes -- a single value has no
    comma and comes back unchanged -- so this is safe whichever way ABDM
    sends it.
    """
    found: set[str] = set()
    for ctx in contexts or []:
        if not isinstance(ctx, dict):
            continue
        raw = ctx.get("hiType")
        if not isinstance(raw, str):
            continue
        for part in raw.split(","):
            cleaned = part.strip()
            if cleaned:
                found.add(cleaned)
    return sorted(found)


# ABDM's "you already have this locker" rejection. CONFIRMED LIVE
# 2026-09-22 -- 8.3.18 called twice returns HTTP 400 with body
# [{"error": {"code": "ABDM-1151: ", "message": "Health locker is already
# setup for the user"}}]. Note the trailing space/colon inside the code
# and the LIST wrapper, both matched loosely below rather than exactly.
_ALREADY_SETUP_CODE = "ABDM-1151"


def _is_already_setup(body: Any) -> bool:
    """True for ABDM's already-set-up rejection, in either shape it may arrive."""
    if isinstance(body, list):
        return any(_is_already_setup(item) for item in body)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            haystack = f"{error.get('code') or ''} {error.get('message') or ''}"
        else:
            haystack = f"{body.get('code') or ''} {body.get('message') or ''}"
        return _ALREADY_SETUP_CODE in haystack or "already setup" in haystack.lower()
    return False


def _has_usable_subscription(entry: dict[str, Any]) -> bool:
    """
    A subscription counts only if it is granted/active AND its period has
    not already ended. The locker's own period runs 100 years, so the
    date check is belt-and-braces rather than a live concern -- but an
    expired-but-still-listed subscription would otherwise silently look
    usable.
    """
    if _status_of(entry) not in _USABLE_STATUSES:
        return False

    period = entry.get("period") or {}
    if not period:
        sources = entry.get("includedSources") or []
        if isinstance(sources, list) and sources and isinstance(sources[0], dict):
            period = sources[0].get("period") or {}

    period_to = _parse_iso(period.get("to"))
    if period_to is not None and period_to <= datetime.now(timezone.utc):
        return False
    return True


# =============================================================================
# Ensure on login
# =============================================================================

def get_locker_status(settings: Settings, x_auth_token: str, patient_id: str) -> dict[str, Any]:
    """
    Reads ABDM's own view of this patient's locker and reconciles it with
    ours. NEVER creates anything -- the opt-in screen decides that.

    Returns a dict the UI can act on directly:
        {"ok", "lockerId", "lockerConfigured", "lockerPresent",
         "lockerActive", "subscriptionUsable", "needsOptIn", "optInState",
         "subscription", "autoApproval", "error"}

    needsOptIn is the single field the client gates its opt-in screen on.
    It is True when the locker is missing/inactive or has no usable
    subscription AND the patient has not already declined or opted out --
    a patient who said "Not now", paused or revoked is NOT asked again on
    every login, and is never silently re-subscribed (P19 section 3.5).
    """
    locker_id = settings.abdm_health_locker_id
    base: dict[str, Any] = {
        "ok": True,
        "lockerId": locker_id,
        "lockerConfigured": bool(locker_id),
        "lockerPresent": False,
        "lockerActive": False,
        "subscriptionUsable": False,
        "needsOptIn": False,
        "optInState": repo.OPT_IN_PENDING,
        "subscription": None,
        "autoApproval": None,
        "error": None,
    }

    if not locker_id:
        # Deliberately inert rather than falling back to any of the removed
        # self-view workarounds: with no locker configured there is no
        # legitimate way to reach this patient's records.
        base["ok"] = False
        base["error"] = "ABDM_HEALTH_LOCKER_ID is not set -- locker automation is disabled."
        return base

    local = repo.get_patient_locker(patient_id, locker_id) or {}
    base["optInState"] = local.get("optInState") or repo.OPT_IN_PENDING

    lockers = subscription.get_patient_subscribed_lockers(settings, x_auth_token, include_inactive=True)
    if not lockers.ok:
        base["ok"] = False
        base["error"] = f"Could not read subscribed lockers (8.3.16): status={lockers.status_code}"
        return base

    ours = None
    for entry in lockers.body if isinstance(lockers.body, list) else []:
        if isinstance(entry, dict) and entry.get("lockerId") == locker_id:
            ours = entry
            break

    base["lockerPresent"] = ours is not None
    base["lockerActive"] = bool(ours and ours.get("isActive"))

    if base["lockerActive"]:
        details = subscription.get_locker_details(settings, x_auth_token, locker_id)
        if details.ok and isinstance(details.body, dict):
            subs = [s for s in (details.body.get("subscriptions") or []) if _is_ours(s, locker_id)]
            usable = [s for s in subs if _has_usable_subscription(s)]
            approvals = [a for a in (details.body.get("autoApprovals") or [])
                         if isinstance(a, dict) and a.get("hiuId") == locker_id and a.get("isActive")]

            base["subscriptionUsable"] = bool(usable)
            base["subscription"] = usable[0] if usable else (subs[0] if subs else None)
            base["autoApproval"] = approvals[0] if approvals else None

            if usable:
                chosen = usable[0]
                sources = chosen.get("includedSources") or []
                period = (sources[0].get("period") if sources and isinstance(sources[0], dict) else {}) or {}
                repo.upsert_patient_locker(
                    patient_id,
                    locker_id,
                    subscription_id=chosen.get("subscriptionId"),
                    consent_auto_approval_id=(approvals[0].get("autoApprovalId") if approvals else None),
                    status=chosen.get("status"),
                    categories=(sources[0].get("categories") if sources and isinstance(sources[0], dict) else None),
                    period_from=_parse_iso(period.get("from")),
                    period_to=_parse_iso(period.get("to")),
                    detail=details.body,
                )
        else:
            base["error"] = f"Could not read locker details (8.3.17): status={details.status_code}"

    already_decided_no = base["optInState"] in (repo.OPT_IN_DECLINED, repo.OPT_IN_OPTED_OUT)
    base["needsOptIn"] = (not base["subscriptionUsable"]) and not already_decided_no
    return base


def setup_locker_for_patient(settings: Settings, x_auth_token: str, patient_id: str) -> dict[str, Any]:
    """
    The whole of "subscribe this patient", run only after they pressed
    Allow on the opt-in screen.

    ONE CALL DOES EVERYTHING. Setup Locker (8.3.18) returns both
    subscriptionId and consentAutoApprovalId, and the subscription comes
    back already GRANTED -- confirmed live 2026-09-22, granted 57 ms after
    creation with no approve step. There is deliberately no 8.3.2 init
    here; that route exists only as recovery (see
    recover_subscription_via_init()) and for genuine third-party HIUs.
    """
    locker_id = settings.abdm_health_locker_id
    if not locker_id:
        return {"ok": False, "error": "ABDM_HEALTH_LOCKER_ID is not set.", "status": None, "body": None}

    repo.set_opt_in(patient_id, locker_id, repo.OPT_IN_ALLOWED)

    result = subscription.setup_locker(settings, x_auth_token, locker_id)

    if not result.ok:
        # ABDM-1151 "Health locker is already setup for the user" is NOT a
        # failure -- it means the thing we wanted is already true.
        # CONFIRMED LIVE 2026-09-22 (P19 live test 3): calling 8.3.18 again
        # for a patient who already has an active locker returns HTTP 400
        # with this code and, importantly, creates NOTHING -- the
        # subscription and auto-approval counts were identical before and
        # after, same ids. So it is safe, just useless as a recovery path.
        # Treated as success here and reconciled from 8.3.17 below, rather
        # than showing the patient an error for an already-working locker.
        if _is_already_setup(result.body):
            log_phase(f"Locker already set up for {patient_id} (ABDM-1151) -- reconciling from 8.3.17 instead.")
            status = get_locker_status(settings, x_auth_token, patient_id)
            return {
                "ok": True,
                "status": result.status_code,
                "body": result.body,
                "alreadySetUp": True,
                "local": repo.get_patient_locker(patient_id, locker_id),
                "lockerStatus": status,
                "error": None,
            }

        log_error(f"Setup Locker failed for {patient_id}: status={result.status_code}")
        return {"ok": False, "status": result.status_code, "body": result.body,
                "error": f"Setup Locker (8.3.18) failed with status {result.status_code}."}

    body = result.body if isinstance(result.body, dict) else {}
    row = repo.upsert_patient_locker(
        patient_id,
        locker_id,
        subscription_id=body.get("subscriptionId"),
        consent_auto_approval_id=body.get("consentAutoApprovalId"),
        detail=body,
    )
    log_phase(
        f"Locker set up for {patient_id}: subscriptionId={body.get('subscriptionId')} "
        f"consentAutoApprovalId={body.get('consentAutoApprovalId')}"
    )
    return {"ok": True, "status": result.status_code, "body": body, "local": row, "error": None}


def recover_subscription_via_init(settings: Settings, patient_id: str) -> dict[str, Any]:
    """
    RECOVERY ONLY -- for a locker that is present and active but whose
    subscription is missing, revoked or expired.

    Raises 8.3.2 as the locker (hiu.id = our locker id, LINK + DATA, no
    hips so it covers every hospital, a far-future period end), mirroring
    what Setup Locker itself created: purpose PATRQT, NOT the spec's and
    Postman's own CAREMGT examples, because the auto-approval policy
    ABDM built for this locker is PATRQT and a consent has to match it.

    THIS IS THE CONFIRMED RECOVERY PATH (settled by P19 live test 3,
    2026-09-22). The alternative -- simply calling Setup Locker again --
    was tested once, deliberately, on a patient who already had an active
    locker: ABDM rejects it with HTTP 400 {"code": "ABDM-1151: ",
    "message": "Health locker is already setup for the user"}. The
    rejection is clean (subscription and auto-approval counts and ids were
    byte-identical before and after -- no duplicate, no side effect), but
    it means Setup Locker cannot repair a locker whose subscription has
    gone missing, revoked or expired. 8.3.2 init as the locker is the only
    route left, which is what this function does.
    """
    locker_id = settings.abdm_health_locker_id
    if not locker_id:
        return {"ok": False, "error": "ABDM_HEALTH_LOCKER_ID is not set."}

    now = datetime.now(timezone.utc)
    result = subscription.initiate_subscription_request(
        settings,
        patient_id=patient_id,
        hiu_id=locker_id,
        categories=["LINK", "DATA"],
        period_from=_iso(now + timedelta(minutes=1)),
        period_to=_iso(now.replace(year=now.year + 100)),
        hips=None,
        purpose_text=subscription.LOCKER_PURPOSE_TEXT,
        purpose_code=subscription.LOCKER_PURPOSE_CODE,
    )
    return {"ok": result.ok, "status": result.status_code, "body": result.body, "error": result.error}


# =============================================================================
# Alert -> records
# =============================================================================

# How far back a locker-raised consent asks for data. The alert itself
# names care contexts but never says how old the records in them are, and
# ABDM requires a concrete dateRange, so this has to be chosen.
_CONSENT_LOOKBACK_DAYS = 365 * 5

# How long the locker keeps fetched data before ABDM expects it erased.
_DATA_ERASE_DAYS = 365


def _consent_date_range(patient_locker: dict[str, Any] | None) -> tuple[str, str]:
    """
    The dateRange a locker-raised consent asks for.

    OPEN QUESTION, DELIBERATELY NOT GUESSED AWAY: the auto-approval policy
    ABDM created for this locker has period.from = the moment Setup Locker
    ran (10:50:38Z on 2026-09-22 for the first patient), roughly a minute
    AFTER the subscription's own start. If ABDM reads that period as the
    permitted DATA date range rather than the policy's validity window,
    then any consent covering historical records -- which is every consent
    the initial sync raises, and most LINK alerts -- falls outside it and
    will NOT auto-approve.

    This asks for what the records actually need (a real look-back) rather
    than silently clamping into the policy window to force an approval
    that would then cover no useful data. If ABDM rejects or fails to
    auto-approve it, the alert stays at CONSENT_REQUESTED with that fact
    recorded, which is the visible failure P19 section 3.5 asks for. Live
    tests 5 and 7 settle which reading is right.
    """
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=_CONSENT_LOOKBACK_DAYS)

    period_from = _parse_iso((patient_locker or {}).get("periodFrom"))
    if period_from is not None and period_from > start:
        # Recorded, not applied -- see this function's own docstring.
        log_phase(
            f"Locker consent look-back {_iso(start)} predates the auto-approval "
            f"policy start {_iso(period_from)}; requesting the full range anyway "
            f"so a non-approval is visible rather than silently narrowed."
        )
    return _iso(start), _iso(now)


def _raise_locker_consent(
    settings: Settings,
    patient_id: str,
    hip_id: str,
    contexts: list[dict[str, Any]],
    hi_types: list[str],
    event_id: str | None = None,
) -> dict[str, Any]:
    """
    Raises a consent request AS THE LOCKER, scoped to the alert's own
    hospital and care contexts.

    Everything here is chosen to match the auto-approval policy read back
    from 8.3.17, because a consent that does not match it will sit
    unapproved forever: hiu.id = our locker id, purpose PATRQT ("Self
    Requested"), HI types drawn from the alert and intersected with the
    eight the policy covers.

    P20 -- uses aegle_phr's OWN hiu_client.initiate_consent_request(), not
    repo/'s. Same endpoint and the same proven payload; what changed is
    that the call is now correlated in this app's own
    locker_pending_request table, carrying event_id, so the on-init /
    notify / on-fetch callbacks can advance THIS alert. Under repo/'s
    version that correlation did not exist and the alert stopped at
    CONSENT_REQUESTED forever.
    """
    locker_id = settings.abdm_health_locker_id
    local = repo.get_patient_locker(patient_id, locker_id)
    date_from, date_to = _consent_date_range(local)

    care_contexts: list[dict[str, str]] = []
    for ctx in contexts or []:
        if not isinstance(ctx, dict):
            continue
        for cc in ctx.get("careContexts") or []:
            if isinstance(cc, dict) and cc.get("careContextReference"):
                care_contexts.append({
                    "patientReference": cc.get("patientReference"),
                    "careContextReference": cc.get("careContextReference"),
                })

    try:
        result = hiu_client.initiate_consent_request(
            settings,
            hiu_id=locker_id,
            patient_abha_address=patient_id,
            requester_name="Aegle Urgent Care Health Locker",
            requester_identifier_type="ABHA-ADDRESS",
            requester_identifier_value=patient_id,
            requester_identifier_system="https://healthid.abdm.gov.in",
            purpose_text=subscription.LOCKER_PURPOSE_TEXT,
            purpose_code=subscription.LOCKER_PURPOSE_CODE,
            purpose_ref_uri=subscription.PURPOSE_REF_URI,
            hi_types=hi_types,
            date_range_from=date_from,
            date_range_to=date_to,
            data_erase_at=_iso(datetime.now(timezone.utc) + timedelta(days=_DATA_ERASE_DAYS)),
            hip_id=hip_id,
            care_contexts=care_contexts or None,
            alert_event_id=event_id,
        )
    except Exception as exc:
        return {"ok": False, "error": f"initiate_consent_request() failed: {type(exc).__name__}: {exc}"}

    if not result.ok:
        return {
            "ok": False,
            "status": result.status_code,
            "error": result.error or f"consent init returned {result.status_code}",
            "body": result.body,
        }

    return {"ok": True, "status": result.status_code, "error": None}


def process_link_alert(
    settings: Settings,
    patient_id: str,
    hip_id: str,
    contexts: list[dict[str, Any]],
    event_id: str,
) -> None:
    """
    LINK -- a new visit was linked, so raise a consent for it.

    Spec section 8.1: "If the subscription category is LINK - Health
    locker/PHR should initiate a consent request for the notified care
    context."

    P20 -- the rest of the chain (on-init, notify, fetch, on-fetch, data
    request, push) is now this app's own, in
    aegle_phr/callbacks/hiu_services.py, correlated by the event_id
    carried on the outbound call's pending row. It no longer depends on
    repo/'s HIU code, nor on that project's per-HIU auto-trigger
    allowlist.
    """
    hi_types = hi_types_from_contexts(contexts) or list(subscription.ALL_HI_TYPES)

    result = _raise_locker_consent(settings, patient_id, hip_id, contexts, hi_types, event_id=event_id)
    if result.get("ok"):
        repo.update_alert_state(event_id, repo.ALERT_CONSENT_REQUESTED)
        log_phase(f"LINK event {event_id}: locker consent requested for patient={patient_id} hip={hip_id} hiTypes={hi_types}")
    else:
        repo.update_alert_state(event_id, repo.ALERT_FAILED, failure_reason=str(result.get("error")))
        log_error(f"LINK event {event_id}: locker consent request failed: {result.get('error')}")


def process_data_alert(
    settings: Settings,
    patient_id: str,
    hip_id: str,
    contexts: list[dict[str, Any]],
    event_id: str,
) -> None:
    """
    DATA -- new data on a visit we may already hold consent for.

    Spec section 8.1: "check if any existing consent request is available
    ... and use the same to initiate the data-request". If none covers it,
    a fresh locker consent is raised -- the LINK path's behaviour -- rather
    than leaving the data unreachable.

    P20 -- reuse looks at the ARTEFACTS WE HOLD
    (locker_hiu_repository.find_usable_artefact) rather than at our alert
    log: an artefact carries the permission window and hiTypes ABDM
    actually granted, so "can this consent serve this pull" is a fact we
    can check rather than an assumption.

    EXPECT IT TO FALL THROUGH. Confirmed live 2026-09-23: ABDM rejects any
    consent whose dateRange.to is in the future (ABDM-9999, "Date must be
    a present/before date"), so every consent's range ends when it was
    raised and no existing consent can ever cover NEW data. Raising a
    fresh consent per alert is what ABDM's design requires, not a missed
    optimisation -- see find_usable_artefact()'s own docstring for the
    full reasoning and the one case where reuse could still apply.
    """
    hi_types = hi_types_from_contexts(contexts)
    hi_type = hi_types[0] if hi_types else None

    artefact = hiu_repo.find_usable_artefact(patient_id, hip_id, hi_type)
    if artefact and artefact.get("consentId"):
        consent_id = artefact["consentId"]
        # The artefact's own approved window, not our preferred look-back:
        # ABDM rejects (ABDM-1063) anything outside what was granted.
        date_from = artefact.get("permissionFrom")
        date_to = artefact.get("permissionTo")
        try:
            result = hiu_client.request_health_information(
                settings,
                hiu_id=artefact.get("hiuId") or settings.abdm_health_locker_id,
                consent_id=consent_id,
                hip_id=hip_id,
                date_range_from=date_from,
                date_range_to=date_to,
                patient_id=patient_id,
                alert_event_id=event_id,
            )
        except Exception as exc:
            repo.update_alert_state(event_id, repo.ALERT_FAILED, failure_reason=f"{type(exc).__name__}: {exc}")
            log_error(f"DATA event {event_id}: data request on reused consent {consent_id} failed: {exc}")
            return

        if result.ok:
            repo.update_alert_state(
                event_id,
                repo.ALERT_DATA_REQUESTED,
                consent_id=consent_id,
                health_information_request_id=(result.body or {}).get("requestId"),
            )
            log_phase(f"DATA event {event_id}: reused granted consent {consent_id} and requested data")
        else:
            reason = result.error or f"data request returned {result.status_code}"
            repo.update_alert_state(event_id, repo.ALERT_FAILED, failure_reason=reason)
            log_error(f"DATA event {event_id}: data request on reused consent failed: {reason}")
        return

    log_phase(f"DATA event {event_id}: no artefact we hold covers hip={hip_id} hiType={hi_type} -- raising a new consent")
    process_link_alert(settings, patient_id, hip_id, contexts, event_id)


# =============================================================================
# Initial sync
# =============================================================================

def run_initial_sync(settings: Settings, x_auth_token: str, patient_id: str, force: bool = False) -> dict[str, Any]:
    """
    One-off backfill of care contexts linked BEFORE the subscription existed.

    WHY IT IS NEEDED: 8.3.11 alerts only fire for links made AFTER the
    subscription. Without this, a patient who already had records linked --
    which is every patient this project has tested with -- would see an
    empty app forever and nothing would look broken.

    ONE CONSENT PER HOSPITAL, not per care context: the consent request
    carries a careContexts list, so one request covers everything already
    linked at that HIP. Each is logged in the SAME alert log the live
    alerts use, under a synthetic event id ("initial-sync:<patient>:<hip>"),
    so it dedupes and shows its processing state exactly like a real
    alert -- per P19 section 3.5, "record it the same way, so it runs once
    per patient".

    Runs only when the patient has a usable locker subscription; without
    one the consents would have nothing to auto-approve them.
    """
    locker_id = settings.abdm_health_locker_id
    local = repo.get_patient_locker(patient_id, locker_id)

    if not local or (local.get("optInState") != repo.OPT_IN_ALLOWED):
        return {"ok": False, "error": "Patient has not opted in to the locker.", "skipped": True}

    if not force and local.get("initialSyncState") in (repo.SYNC_RUNNING, repo.SYNC_DONE):
        return {"ok": True, "skipped": True, "reason": f"initial sync already {local.get('initialSyncState')}",
                "initialSyncState": local.get("initialSyncState")}

    repo.upsert_patient_locker(patient_id, locker_id, initial_sync_state=repo.SYNC_RUNNING)

    from aegle_phr.phr import links

    result = links.get_all_linked_records(settings, x_auth_token)
    if not result.ok or not isinstance(result.body, dict):
        repo.upsert_patient_locker(
            patient_id, locker_id,
            initial_sync_state=repo.SYNC_FAILED,
            initial_sync_detail={"error": f"get_all_linked_records failed: status={result.status_code}"},
        )
        return {"ok": False, "error": f"Could not read linked records: status={result.status_code}"}

    # Group every already-linked care context by the HIP holding it.
    # Shape confirmed live: patient.links[].{hip{id}, hiType, referenceNumber,
    # careContexts[].referenceNumber}. NOTE the care context's key is
    # "referenceNumber" here, while a consent's careContexts want
    # "careContextReference" -- mapped below, not assumed identical.
    by_hip: dict[str, dict[str, Any]] = {}
    for link in ((result.body.get("patient") or {}).get("links") or []):
        if not isinstance(link, dict):
            continue
        hip_id = (link.get("hip") or {}).get("id")
        if not hip_id:
            continue
        bucket = by_hip.setdefault(hip_id, {"careContexts": [], "hiTypes": set(), "seen": set()})
        # Same comma-joined defence as the alert path -- see
        # hi_types_from_contexts(). The linked-records feed has only ever
        # been seen with single values, but there is no reason to parse
        # the same field two different ways.
        for part in str(link.get("hiType") or "").split(","):
            cleaned = part.strip()
            if cleaned:
                bucket["hiTypes"].add(cleaned)
        patient_reference = link.get("referenceNumber")
        for cc in link.get("careContexts") or []:
            ref = cc.get("referenceNumber") if isinstance(cc, dict) else None
            if ref and ref not in bucket["seen"]:
                bucket["seen"].add(ref)
                bucket["careContexts"].append({"patientReference": patient_reference, "careContextReference": ref})

    outcomes: list[dict[str, Any]] = []
    for hip_id, bucket in by_hip.items():
        event_id = f"initial-sync:{patient_id}:{hip_id}"
        contexts = [{"careContexts": bucket["careContexts"], "hiType": hi} for hi in sorted(bucket["hiTypes"])] or \
                   [{"careContexts": bucket["careContexts"], "hiType": None}]

        _, is_new = repo.record_alert_if_new(
            event_id, patient_id,
            locker_id=locker_id, category="INITIAL_SYNC", hip_id=hip_id, contexts=contexts,
            detail={"source": "initial_sync", "careContextCount": len(bucket["careContexts"])},
        )
        if not is_new and not force:
            outcomes.append({"hipId": hip_id, "skipped": True, "reason": "already synced"})
            continue

        hi_types = sorted(bucket["hiTypes"]) or list(subscription.ALL_HI_TYPES)
        # event_id MUST be threaded through (P20). Without it the consent
        # goes out uncorrelated and every callback in the chain has no
        # alert to advance -- the initial-sync rows would sit at
        # CONSENT_REQUESTED forever, which is the precise defect P20
        # exists to remove. The LINK path passes it; this one was missed.
        raised = _raise_locker_consent(settings, patient_id, hip_id, contexts, hi_types, event_id=event_id)
        if raised.get("ok"):
            repo.update_alert_state(event_id, repo.ALERT_CONSENT_REQUESTED)
            outcomes.append({"hipId": hip_id, "ok": True, "careContexts": len(bucket["careContexts"]), "hiTypes": hi_types})
        else:
            repo.update_alert_state(event_id, repo.ALERT_FAILED, failure_reason=str(raised.get("error")))
            outcomes.append({"hipId": hip_id, "ok": False, "error": raised.get("error")})

    any_failed = any(o.get("ok") is False for o in outcomes)
    repo.upsert_patient_locker(
        patient_id, locker_id,
        initial_sync_state=repo.SYNC_FAILED if any_failed else repo.SYNC_DONE,
        initial_sync_detail={"hips": outcomes},
    )
    log_phase(f"Initial sync for {patient_id}: {len(outcomes)} hospital(s), failed={any_failed}")
    return {"ok": not any_failed, "hips": outcomes,
            "initialSyncState": repo.SYNC_FAILED if any_failed else repo.SYNC_DONE}
