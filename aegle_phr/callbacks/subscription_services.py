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

from aegle_phr.phr import locker_repository, locker_service, subscription
from aegle_phr.phr.subscription_repository import (
    get_by_subscription_request_id,
    link_subscription_request_id,
    update_status_by_subscription_request_id,
)
from aegle_phr.settings import Settings


def handle_subscription_on_init(settings: Settings, payload: Any, request_id_header: str | None) -> None:
    """
    8.3.3 -- correlates the callback's response.requestId back to the
    pending row saved when the subscription was initiated (mirrors repo/
    server/callbacks/services/consent_init_on_init_service.py's identical
    correlation shape for consent's 6.5).

    NO ACKNOWLEDGEMENT IS SENT HERE (corrected in P19). Spec section 8.2's
    own sequence diagrams show init -> on-init with nothing sent back;
    8.3.6 acknowledges the DECISION callback (hiu/notify) instead, and now
    fires from handle_subscription_notify() below. P13 called 8.3.6 from
    here, which both acked something ABDM never asked to have acked and
    left the real GRANTED/DENIED notification unacknowledged.

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


def handle_subscription_notify(settings: Settings, payload: Any, request_id_header: str | None = None) -> None:
    """
    8.3.5/8.3.8/8.3.10 -- ONE shared callback URL for three outcomes
    (approve/deny/edit-result), distinguished by notification.status.

    ACKNOWLEDGES VIA 8.3.6 (moved here in P19 from the on-init handler --
    see handle_subscription_on_init()'s own docstring). Spec section 8.2's
    sequence diagrams put the only acknowledgement of this exchange after
    the decision callback, not after on-init. The ack echoes THIS
    callback's own REQUEST-ID header back as response.requestId.
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
    else:
        log_phase(f"Subscription {subscription_request_id} status updated to {status} (subscriptionId={subscription_id})")

    # 8.3.6 -- acknowledge the DECISION, regardless of whether we could
    # correlate it locally above. ABDM asked to be acked for this
    # notification; failing to ack because OUR OWN bookkeeping has no
    # matching row would leave ABDM retrying a callback we did receive.
    ack_result = subscription.ack_subscription_notify(
        settings,
        subscription_request_id=subscription_request_id,
        response_request_id=request_id_header or subscription_request_id,
    )
    if not ack_result.ok:
        log_error(
            f"Failed to ack subscription decision for subscriptionRequestId={subscription_request_id}: "
            f"status={ack_result.status_code} error={ack_result.error}"
        )
    else:
        log_phase(f"Acked subscription decision ({status}) for subscriptionRequestId={subscription_request_id}")


def handle_subscription_care_context_notify(settings: Settings, payload: Any, request_id_header: str | None) -> None:
    """
    8.3.11 -- "new LINK/DATA available" event notify. Acks via 8.3.12,
    records the alert (deduped on ABDM's own event.id), then hands off to
    locker_service for section 8.1's own next step per category:
      LINK -> raise a consent request AS THE LOCKER for the notified care
              contexts, matching the locker's auto-approval policy so it
              grants without troubling the patient.
      DATA -> reuse an existing GRANTED locker-raised consent covering
              this care context / HI type, and only raise a new one if
              none does.

    REWIRED IN P19: this used to call data_flow.request_self_view_consent()
    (raising consents under a HIP id as a stand-in HIU) and had no alert
    log or dedupe at all. Both trigger helpers that did that are gone --
    see CC_PROMPT_P19 section 5.

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

    # DEDUPE (P19). Recorded AFTER the ack above and BEFORE any processing:
    # ABDM redelivers an alert it believes went unacknowledged, so a repeat
    # must still be acked (done) but must never raise a second consent
    # request for the same event. record_alert_if_new() is an ON CONFLICT
    # insert keyed on ABDM's own event.id, so even two concurrent
    # deliveries cannot both be treated as new.
    try:
        alert, is_new = locker_repository.record_alert_if_new(
            event_id,
            patient_id,
            subscription_id=event.get("subscriptionId"),
            locker_id=settings.abdm_health_locker_id or None,
            category=category,
            hip_id=hip_id,
            contexts=contexts,
            detail=payload,
        )
    except Exception as exc:
        log_error(f"Could not record care-context alert {event_id}: {exc}")
        return

    if not is_new:
        log_phase(
            f"Care-context notify event {event_id} is a REDELIVERY "
            f"(already {alert.get('processingState')}) -- acked again, not reprocessed."
        )
        return

    try:
        if category == "LINK":
            locker_service.process_link_alert(settings, patient_id, hip_id, contexts, event_id)
        elif category == "DATA":
            locker_service.process_data_alert(settings, patient_id, hip_id, contexts, event_id)
        else:
            log_error(f"Care-context notify event {event_id} has unrecognized category={category!r} -- open item, no action taken.")
            locker_repository.update_alert_state(
                event_id, locker_repository.ALERT_FAILED,
                failure_reason=f"unrecognized category {category!r}",
            )
    except Exception as exc:
        # Defensive per the task spec: a failure applying section 8.1's own
        # next-step logic must not propagate past this handler (the ack
        # above has already happened) -- recorded on the alert row instead,
        # never swallowed.
        log_error(f"Failed to apply follow-up action for care-context notify event {event_id} (category={category}): {exc}")
        try:
            locker_repository.update_alert_state(
                event_id, locker_repository.ALERT_FAILED, failure_reason=str(exc)
            )
        except Exception:
            pass
