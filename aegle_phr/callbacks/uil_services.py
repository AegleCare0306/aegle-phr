"""
P15 -- real per-callback logic for the three User-Initiated Linking
(spec §10) callback types. dispatcher.py's dispatch() keeps archiving
unconditionally and staying business-logic-free (its own stated contract)
-- these functions are called AFTER that, from router.py, each wrapped in
its own try/except so a bug here can never surface to ABDM as a non-2xx
(same "never raise past the callback route" contract dispatch() itself
upholds). Mirrors aegle_phr/callbacks/subscription_services.py's own shape
exactly, per the task spec.

UNLIKE subscription_on_init (8.3.3, which requires a SEPARATE outbound
8.3.6 ack call), none of the three UIL callbacks below have their own
outbound ack endpoint in the spec -- router.py's own generic
{"status": "OK"} response IS the acknowledgement ABDM needs. So every
function here just correlates the callback back to its own
UilLinkRequest row and updates it -- no outbound ABDM call is made from
this module at all.

Plain, sync functions -- matches this whole package's own convention
(router.py's own docstring: "Every route below is a plain `def`, not
`async def`").
"""

from typing import Any

from abdm_core.observability.flow_logger import log_error, log_phase

from aegle_phr.phr.uil_repository import update_by_request_id
from aegle_phr.settings import Settings


def handle_on_discover(settings: Settings, payload: Any, request_id_header: str | None) -> None:
    """
    10.3.4 -- correlates the callback's response.requestId back to the row
    save_new_request() created right before the matching discover() call.

    Confirmed inbound body shape (spec's own documented example):
        {"transactionId": "...",
         "patient": [{"referenceNumber": "...", "display": "...",
                       "careContexts": [...], "hiType": "...", "count": N}],
         "response": {"requestId": "..."}}
    or, on no match / an error:
        {"error": {"code": "ABDM-1010", "message": "Patient not found"},
         "response": {"requestId": "..."}}
    """
    if not isinstance(payload, dict):
        log_error("uil on_discover payload is not a dict -- cannot process.")
        return

    our_request_id = (payload.get("response") or {}).get("requestId")
    if not our_request_id:
        log_error("uil on_discover callback missing response.requestId -- cannot correlate to a pending discover call.")
        return

    error = payload.get("error")
    status = "ERROR" if error else "DISCOVERED"

    row = update_by_request_id(our_request_id, status=status, detail=payload)
    if row is None:
        log_error(f"No pending UIL discover row found for requestId {our_request_id}.")
        return

    if error:
        log_error(f"UIL discover {our_request_id} returned an error: {error}")
    else:
        transaction_id = payload.get("transactionId")
        match_count = len(payload.get("patient") or [])
        log_phase(f"UIL discover {our_request_id} complete: transactionId={transaction_id} matches={match_count}")


def handle_on_init(settings: Settings, payload: Any, request_id_header: str | None) -> None:
    """
    10.3.8 -- correlates back to the row save_new_request() created right
    before the matching link_init() call, and captures link.referenceNumber
    (needed for the confirm step) onto that same row.

    Confirmed inbound body shape (spec's own documented example):
        {"transactionId": "...",
         "link": {"referenceNumber": "...", "authenticationType": "...",
                   "meta": {"communicationMedium": "...", "communicationHint": "...",
                             "communicationExpiry": "..."}},
         "response": {"requestId": "..."}}
    or an error, same shape as on-discover's own.
    """
    if not isinstance(payload, dict):
        log_error("uil on_init payload is not a dict -- cannot process.")
        return

    our_request_id = (payload.get("response") or {}).get("requestId")
    if not our_request_id:
        log_error("uil on_init callback missing response.requestId -- cannot correlate to a pending link-init call.")
        return

    error = payload.get("error")
    link_ref_number = None
    if not error:
        link = payload.get("link") or {}
        link_ref_number = link.get("referenceNumber")
        if not link_ref_number:
            log_error(f"uil on_init callback for requestId {our_request_id} has no error but also no link.referenceNumber -- cannot proceed to confirm.")

    status = "ERROR" if error else "INITIATED"
    row = update_by_request_id(our_request_id, status=status, detail=payload, link_ref_number=link_ref_number)
    if row is None:
        log_error(f"No pending UIL link-init row found for requestId {our_request_id}.")
        return

    if error:
        log_error(f"UIL link-init {our_request_id} returned an error: {error}")
    else:
        log_phase(f"UIL link-init {our_request_id} complete: linkRefNumber={link_ref_number}")


def handle_on_confirm(settings: Settings, payload: Any, request_id_header: str | None) -> None:
    """
    10.3.12 -- correlates back to the row save_new_request() created right
    before the matching link_confirm() call. This is the actual "you now
    have linked records" moment -- HomeScreen.tsx's existing
    getAllLinkedRecords() (spec §9.3.5) will show the newly-linked care
    context on its own next fetch; nothing here writes into that flow's
    own data, they are genuinely independent ABDM-side records of the same
    underlying fact.

    Confirmed inbound body shape (spec's own documented example):
        {"patient": [{"referenceNumber": "...", "careContexts": [...], ...}],
         "response": {"requestId": "..."}}
    or an error, same shape as the other two callbacks.
    """
    if not isinstance(payload, dict):
        log_error("uil on_confirm payload is not a dict -- cannot process.")
        return

    our_request_id = (payload.get("response") or {}).get("requestId")
    if not our_request_id:
        log_error("uil on_confirm callback missing response.requestId -- cannot correlate to a pending link-confirm call.")
        return

    error = payload.get("error")
    status = "ERROR" if error else "CONFIRMED"

    row = update_by_request_id(our_request_id, status=status, detail=payload)
    if row is None:
        log_error(f"No pending UIL link-confirm row found for requestId {our_request_id}.")
        return

    if error:
        log_error(f"UIL link-confirm {our_request_id} returned an error: {error}")
    else:
        linked_count = len(payload.get("patient") or [])
        log_phase(f"UIL link-confirm {our_request_id} complete: {linked_count} patient entries now linked.")
