"""
P13 -- real per-callback logic for the three Subscription Flow (spec §8)
callback types. dispatcher.py's dispatch() keeps archiving unconditionally
and staying business-logic-free (its own stated contract) -- these
functions are called AFTER that, from router.py, each wrapped in its own
try/except so a bug here can never surface to ABDM as a non-2xx (same
"never raise past the callback route" contract dispatch() itself upholds).

Plain, sync functions -- matches this whole package's own convention
(router.py's own docstring: "Every route below is a plain `def`, not
`async def`" -- blocking DB + blocking requests belong in a threadpool,
not the event loop). repo/'s own async M3 callback services are NOT the
template to copy verbatim here for that reason, even though the
CORRELATION shape they use is (see each function's own docstring for
which repo/ file it mirrors).
"""

from typing import Any

from abdm_core.observability.flow_logger import log_error, log_phase

from aegle_phr.phr import subscription
from aegle_phr.phr.subscription_repository import (
    get_by_subscription_request_id,
    link_subscription_request_id,
    update_status_by_subscription_request_id,
)
from aegle_phr.settings import Settings


def handle_subscription_on_init(settings: Settings, payload: Any, request_id_header: str | None) -> None:
    """
    8.3.3 -- correlates the callback's response.requestId back to the row
    saved by data_flow.py's own ensure_self_subscription() (mirrors repo/
    server/callbacks/services/consent_init_on_init_service.py's identical
    correlation shape for consent's 6.5), then calls 8.3.6 to ack receipt.

    Confirmed inbound body shape (spec 8.3.3's own documented example):
        {"subscriptionRequest": {"id": "..."}, "response": {"requestId": "..."}}
    """
    if not isinstance(payload, dict):
        log_error("subscription_on_init payload is not a dict -- cannot process.")
        return

    our_request_id = (payload.get("response") or {}).get("requestId")
    if not our_request_id:
        log_error("subscription_on_init callback missing response.requestId -- cannot correlate to a pending subscription request.")
        return

    subscription_request = payload.get("subscriptionRequest") or {}
    subscription_request_id = subscription_request.get("id")
    if not subscription_request_id:
        log_error(f"subscription_on_init callback missing subscriptionRequest.id for requestId {our_request_id}.")
        return

    row = link_subscription_request_id(our_request_id, subscription_request_id, detail=payload)
    if row is None:
        log_error(f"No pending subscription request found for requestId {our_request_id}.")
        return

    log_phase(f"subscriptionRequestId {subscription_request_id} recorded for requestId {our_request_id}")

    # ack_subscription_on_init() echoes ABDM's OWN REQUEST-ID header from
    # THIS inbound callback back as response.requestId -- CONFIRMED via
    # the proven, already-live analogous consent pattern (see
    # subscription.py's own ack_subscription_on_init() docstring). Falls
    # back to our own request_id if the header is somehow missing rather
    # than skipping the ack outright -- ABDM still gets an ack either way.
    ack_result = subscription.ack_subscription_on_init(
        settings,
        subscription_request_id=subscription_request_id,
        response_request_id=request_id_header or our_request_id,
    )
    if not ack_result.ok:
        log_error(f"Failed to ack subscription on-init for subscriptionRequestId={subscription_request_id}: status={ack_result.status_code} body={ack_result.body} error={ack_result.error}")
    else:
        log_phase(f"Acked subscription on-init for subscriptionRequestId={subscription_request_id}")


def handle_subscription_notify(settings: Settings, payload: Any) -> None:
    """
    8.3.5/8.3.8/8.3.10 -- ONE shared callback URL for three outcomes
    (approve/deny/edit-result), distinguished by notification.status.
    Mirrors repo/server/callbacks/services/consent_hiu_notify_service.py's
    shape for an analogous multi-outcome single-URL callback: branch on
    status, update local state, no outbound ABDM call needed here (this
    callback's own documented "Response" is just what OUR endpoint's ack
    body looks like, not a further outbound call -- router.py's own
    generic {"status": "OK"} ack already covers that).

    Confirmed inbound body shape (spec 8.3.5/8.3.8/8.3.10's own examples,
    all sharing the outer `notification` wrapper):
        {"notification": {"subscriptionRequestId": "...", "status": "GRANTED", "subscription": {...}}}
        {"notification": {"subscriptionRequestId": "...", "status": "DENIED", "reason": "..."}}
    Spec's own examples are inconsistent about the exact enum (says
    DENIED in the body example, DENY in 8.3.5's own header table) -- this
    stores whatever value actually arrives, unmodified, rather than
    normalizing to a guessed canonical set.
    """
    if not isinstance(payload, dict):
        log_error("subscription_notify payload is not a dict -- cannot process.")
        return

    notification = payload.get("notification") or {}
    subscription_request_id = notification.get("subscriptionRequestId")
    status = notification.get("status")

    if not subscription_request_id or not status:
        log_error(f"subscription_notify callback missing subscriptionRequestId/status: {notification}")
        return

    subscription_id = None
    if isinstance(notification.get("subscription"), dict):
        subscription_id = notification["subscription"].get("id")

    row = update_status_by_subscription_request_id(
        subscription_request_id,
        status=status,
        subscription_id=subscription_id,
        detail=payload,
    )
    if row is None:
        log_error(f"No locally tracked subscription found for subscriptionRequestId={subscription_request_id} -- notify arrived for something we never initiated or never got the on-init callback for.")
        return

    log_phase(f"Subscription {subscription_request_id} status updated to {status} (subscriptionId={subscription_id})")


def handle_subscription_care_context_notify(settings: Settings, payload: Any, request_id_header: str | None) -> None:
    """
    8.3.11 -- "new LINK/DATA available" event notify. Acks via 8.3.12,
    then applies §8.1's own stated next step for the event's own category:
      LINK -> "Health locker/PHR should initiate a consent request for
               the notified care context" -- reuses the EXISTING
               consent-init path (P8/P9's own request_self_view_consent()-
               adjacent machinery), not a new one.
      DATA -> "check if any existing consent request is available ...
               and use the same to initiate the data-request" -- reuses
               the existing 7.3.1 data-flow-request path
               (data_flow.request_health_information()).

    Confirmed inbound body shape (spec 8.3.11's own documented example):
        {"event": {"id", "published", "subscriptionId", "category",
                    "content": {"patient": {"id"}, "hip": {"id"},
                                 "contexts": [{"careContexts": [...], "hiType"}]}}}

    DEFENSIVE, PER THE TASK SPEC: a DATA event with no matching existing
    consent must not crash this handler -- logged as an open item on that
    event, not silently dropped and not raised past this function (the
    ack below still happens regardless, since ABDM must not be left
    thinking we never received the event just because our own downstream
    trigger had nothing to act on yet).
    """
    if not isinstance(payload, dict):
        log_error("subscription_care_context_notify payload is not a dict -- cannot process.")
        return

    event = payload.get("event") or {}
    event_id = event.get("id")
    category = event.get("category")
    content = event.get("content") or {}
    patient_id = (content.get("patient") or {}).get("id")
    hip_id = (content.get("hip") or {}).get("id")

    if not event_id:
        log_error(f"subscription_care_context_notify callback missing event.id: {payload}")
        return

    log_phase(f"Care-context notify received: event={event_id} category={category} patient={patient_id} hip={hip_id}")

    # Ack first -- ABDM needs to know we received the event regardless of
    # whether our own downstream trigger below finds anything to act on.
    ack_result = subscription.ack_subscription_care_context_notify(
        settings,
        event_id=event_id,
        response_request_id=request_id_header or event_id,
    )
    if not ack_result.ok:
        log_error(f"Failed to ack subscription care-context notify for eventId={event_id}: status={ack_result.status_code} body={ack_result.body} error={ack_result.error}")
    else:
        log_phase(f"Acked subscription care-context notify for eventId={event_id}")

    if not patient_id or not hip_id:
        log_error(f"Care-context notify event {event_id} missing patient/hip id -- cannot trigger a follow-up action, open item.")
        return

    contexts = content.get("contexts") or []

    try:
        if category == "LINK":
            _trigger_consent_for_link_event(patient_id, hip_id, contexts, event_id)
        elif category == "DATA":
            _trigger_data_request_for_data_event(settings, patient_id, hip_id, contexts, event_id)
        else:
            log_error(f"Care-context notify event {event_id} has unrecognized category={category!r} -- open item, no action taken.")
    except Exception as exc:
        # Defensive per the task spec: a failure applying §8.1's own
        # next-step logic must not propagate past this handler (the ack
        # above has already happened) -- logged as an open item on this
        # specific event instead.
        log_error(f"Failed to apply follow-up action for care-context notify event {event_id} (category={category}): {exc}")


def _trigger_consent_for_link_event(patient_id: str, hip_id: str, contexts: list[dict[str, Any]], event_id: str) -> None:
    """
    §8.1: "If the subscription category is LINK - Health locker/PHR
    should initiate a consent request for the notified care context."
    Reuses request_self_view_consent() (data_flow.py, P8/P9) -- the
    existing, already-proven self-view consent-init path -- rather than
    building a second one. hi_types comes from whichever hiType(s) this
    event's own contexts carry; falls back to data_flow.py's own broad
    default list if the event carries none (defensive, not expected).
    """
    from aegle_phr.phr import data_flow

    hi_types = sorted({c.get("hiType") for c in contexts if isinstance(c, dict) and c.get("hiType")})
    if not hi_types:
        hi_types = list(data_flow._SELF_VIEW_HI_TYPES)

    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    date_range_from = (now - timedelta(days=365)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    date_range_to = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    result = data_flow.request_self_view_consent(hi_types, date_range_from, date_range_to, patient_id)
    if result.get("ok"):
        log_phase(f"LINK event {event_id}: consent request initiated for patient={patient_id} hip={hip_id}")
    else:
        log_error(f"LINK event {event_id}: consent request initiation failed for patient={patient_id} hip={hip_id}: {result.get('error')}")


def _trigger_data_request_for_data_event(settings: Settings, patient_id: str, hip_id: str, contexts: list[dict[str, Any]], event_id: str) -> None:
    """
    §8.1: "In case subscription category is DATA - then the Health
    locker/PHR should check if any existing consent request is available
    (hiType and duration etc.) and use the same to initiate the
    data-request." Reuses data_flow.request_health_information() (spec
    §7.3.1, already proven working) -- only if a locally-known, GRANTED
    consent already covers this hip_id; otherwise logs an open item
    rather than raising a brand-new consent request itself (that's the
    LINK branch's job, not DATA's -- §8.1 draws this distinction
    explicitly).
    """
    from server.callbacks.repository.hiu_consent_repository import get_all_hiu_consents
    from aegle_phr.phr import data_flow

    all_consents = get_all_hiu_consents()
    matching = [
        (consent_id, c)
        for consent_id, c in all_consents.items()
        if c.get("status") == "GRANTED"
        and (c.get("consent_detail") or {}).get("patient", {}).get("id") == patient_id
        and (c.get("consent_detail") or {}).get("hip", {}).get("id") == hip_id
    ]

    if not matching:
        log_error(f"DATA event {event_id}: no existing GRANTED consent found locally for patient={patient_id} hip={hip_id} -- open item, cannot initiate data-request yet.")
        return

    consent_id, consent = matching[0]
    detail = consent.get("consent_detail") or {}
    hiu_id = (detail.get("hiu") or {}).get("id", "")
    period = (detail.get("permission") or {}).get("dateRange") or {}

    result = data_flow.request_health_information(
        consent_id=consent_id,
        hip_id=hip_id,
        hiu_id=hiu_id,
        date_range_from=period.get("from", ""),
        date_range_to=period.get("to", ""),
    )
    if result.get("ok"):
        log_phase(f"DATA event {event_id}: data-request initiated using existing consent {consent_id}")
    else:
        log_error(f"DATA event {event_id}: data-request initiation failed using existing consent {consent_id}: {result.get('error')}")
