"""
Data Flow (spec section 7): fetching real health-record content for an
already-GRANTED consent.

P20 -- THIS MODULE NO LONGER WRAPS repo/. Until now every function here
imported repo/server/hiu_consent.py and repo/server/hiu_health_information.py
at runtime, with a lazy import and an ImportError branch explaining that the
feature only worked when aegle_phr was mounted inside repo/server/main.py.
That was the single reason a PHR app could not be run on its own: a patient's
locker could raise consents and never complete a data flow without a HIP/HIU
backend sitting in the same process.

The work moved, it was not deleted. The outbound calls live in
aegle_phr/phr/hiu_client.py, the inbound callbacks in
aegle_phr/callbacks/hiu_services.py, and the state in this app's own
locker_pending_request / locker_consent_artefact / locker_health_information
tables. Everything is built on abdm_core, which already carried the retry,
request-id, gateway-token and Fidelius primitives this needs.

WHAT THIS MODULE IS NOW: a thin, stable API-facing layer over those, keeping
the {ok, status, body, error} envelope aegle_phr/api.py's own routes return.
No ABDM payload is constructed here and no correlation is done here.

THE NORMAL PATH DOES NOT COME THROUGH HERE AT ALL. A patient's records reach
this app because their Health Locker holds a subscription, ABDM raises an
8.3.11 alert, and locker_service.py drives consent -> fetch -> data request
automatically (see aegle_phr/phr/locker_service.py). These three functions
are the manual equivalents: useful for testing and for the API surface, not
the route real data takes.

SELF-VIEW MACHINERY REMOVED (P19, 2026-09-22). This module used to carry
four more functions -- request_self_view_consent(),
ensure_self_view_auto_approve(), ensure_self_subscription() and
discover_self_view_consents() -- that between them raised PATRQT self-view
consents under a HIP id borrowed as a stand-in HIU id, set up an
auto-approval policy for them, and, worst of all, DISCOVERED consents ABDM
had granted to a DIFFERENT app entirely (sbx_001, ABDM's own sandbox PHR)
and wrote them into repo/'s consent cache so this app could pull data under
them. All four are gone, and the table that replaced repo/'s cache
(locker_consent_artefact) structurally cannot hold a foreign consent: every
row arrives via an on-fetch callback for a fetch this locker itself made.
"""

from typing import Any

from abdm_core.observability.flow_logger import log_error

from aegle_phr.phr import hiu_client
from aegle_phr.phr import locker_hiu_repository as hiu_repo
from aegle_phr.settings import Settings


def trigger_consent_fetch(settings: Settings, consent_id: str, hiu_id: str) -> dict[str, Any]:
    """
    Manually fetches a GRANTED consent's artefact.

    WHY THIS STILL EXISTS. The normal trigger is
    hiu_services.handle_consent_request_notify(), which fetches every
    artefact the moment ABDM reports a grant. But a notify that never
    arrives has been observed live (2026-09-02: six PATRQT requests all got
    their on-init ack and not one ever produced a notify, all day, while
    CAREMGT requests the same day notified normally). When that happens the
    consent is genuinely GRANTED -- visible in the Consent Manager -- and
    the artefact is simply never fetched, so no data request can cite it.
    This function supplies the trigger the missing callback would have
    supplied. The downstream half (on-fetch storing the artefact, then
    chaining into the data request) is identical either way.

    Returns {"ok": True, "status": 202} on acceptance. The artefact still
    arrives asynchronously on the on-fetch callback -- this does not wait
    for it.
    """
    try:
        result = hiu_client.fetch_consent(settings, hiu_id=hiu_id, consent_id=consent_id)
    except Exception as exc:
        log_error(f"trigger_consent_fetch failed for {consent_id}: {type(exc).__name__}: {exc}")
        return {"ok": False, "status": None, "body": None, "error": f"fetch_consent() failed: {exc}"}

    if not result.ok:
        return {
            "ok": False,
            "status": result.status_code,
            "body": result.body,
            "error": result.error or f"Unexpected status {result.status_code} (expected 202 Accepted).",
        }

    return {"ok": True, "status": result.status_code, "body": result.body, "error": None}


def request_health_information(
    settings: Settings,
    consent_id: str,
    hip_id: str,
    hiu_id: str,
    date_range_from: str,
    date_range_to: str,
) -> dict[str, Any]:
    """
    Starts a section 7.3.1 transfer for an already-GRANTED, already-fetched
    consent.

    BOTH PRECONDITIONS ARE CHECKED LOCALLY FIRST, against the artefact this
    app holds: the consent must be GRANTED, and the requested range must sit
    inside its approved window. ABDM rejects an out-of-range request
    asynchronously, as ABDM-1063 on a callback minutes later, so checking
    here turns a slow mystery into an immediate, specific error.

    Args:
        consent_id: consentDetail.consentId -- NOT consentDetail.requestId.
        hip_id: consentDetail.hip.id from the same artefact.
        hiu_id: consentDetail.hiu.id -- for a locker-raised consent this is
            the locker's own service id.
        date_range_from / date_range_to: ISO 8601, inside the artefact's own
            approved permission.dateRange.

    Returns {"ok": True, "status": 202, "body": {"requestId": ...}} on
    acceptance; the transactionId arrives later on the on-request callback.

    The "we do not hold this consent" case carries a machine-checkable
    "reasonCode": "consent_not_in_local_cache" alongside the prose, so a
    caller can branch on it without string-matching an error message that is
    free to be reworded later.
    """
    try:
        result = hiu_client.request_health_information(
            settings,
            hiu_id=hiu_id,
            consent_id=consent_id,
            hip_id=hip_id,
            date_range_from=date_range_from,
            date_range_to=date_range_to,
        )
    except hiu_client.ConsentNotUsableError as exc:
        response: dict[str, Any] = {"ok": False, "status": None, "body": None, "error": str(exc)}
        if hiu_repo.get_consent_artefact(consent_id) is None:
            response["reasonCode"] = "consent_not_in_local_cache"
        return response
    except Exception as exc:
        log_error(f"request_health_information failed for {consent_id}: {type(exc).__name__}: {exc}")
        return {"ok": False, "status": None, "body": None, "error": str(exc)}

    if not result.ok:
        return {
            "ok": False,
            "status": result.status_code,
            "body": result.body,
            "error": result.error or f"Unexpected status {result.status_code} (expected 202 Accepted).",
        }

    return {
        "ok": True,
        "status": result.status_code,
        "body": {"requestId": (result.body or {}).get("requestId")},
        "error": None,
    }


def get_health_information_status(request_id: str) -> dict[str, Any]:
    """
    One-call poll of the correlation chain: our own request_id -> the
    transactionId the on-request callback linked to it -> the decrypted
    content the HIP pushed under that transaction.

    `body`, on success, is one of:
        {"phase": "pending", "transactionId": None, "careContexts": None}
        {"phase": "transaction_assigned", "transactionId": ..., "careContexts": None}
        {"phase": "complete", "transactionId": ..., "careContexts": {...}}

    "complete" ONLY once the LAST page has arrived. A multi-care-context
    transfer arrives as several pushes, and a caller that stops polling on
    the first non-null careContexts locks in whatever partial subset had
    landed -- confirmed live 2026-09-05, when a 4-care-context transfer
    showed 1, then 2, never all 4. is_transfer_complete() enforces the
    page_number >= page_count - 1 check centrally so no caller has to
    remember it.

    "ok": False only when request_id has no pending session at all -- never
    merely because a transfer is still in progress, which is a normal
    intermediate state, not a failure.
    """
    pending = hiu_repo.get_pending(request_id)
    if pending is None:
        return {
            "ok": False,
            "status": None,
            "body": None,
            "error": (
                f"No health information request found for requestId={request_id!r} -- "
                "it was never initiated from this app."
            ),
        }

    transaction_id = pending.get("transactionId")
    if transaction_id is None:
        return {
            "ok": True,
            "status": 200,
            "body": {"phase": "pending", "transactionId": None, "careContexts": None},
            "error": None,
        }

    stored = hiu_repo.get_health_information(transaction_id)
    if stored is None or not hiu_repo.is_transfer_complete(stored):
        return {
            "ok": True,
            "status": 200,
            "body": {"phase": "transaction_assigned", "transactionId": transaction_id, "careContexts": None},
            "error": None,
        }

    return {
        "ok": True,
        "status": 200,
        "body": {
            "phase": "complete",
            "transactionId": transaction_id,
            "careContexts": stored.get("careContexts") or {},
        },
        "error": None,
    }
