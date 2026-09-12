"""
Single entry point for every inbound ABDM callback this app accepts.

CONTRACT: dispatch() NEVER RAISES. ABDM treats a non-2xx on a callback as
a delivery failure; a bug in our own archiving or (later) handling code
must not surface to ABDM as a 500, because that changes ABDM-side
behaviour (retries, flow abandonment) for a problem that is entirely ours.
Everything is caught, logged, and swallowed. The route still returns the
standard ack.

This is the same shape as the existing backend's dispatch_callback(), and
deliberately so -- but note the difference in what a swallowed failure
costs here: this app archives to Postgres, so a failure means one lost
callback_log row, not a lost flow. Real per-callback handlers arrive in P3
and will need to think about whether "never raise" is still the right
answer for each one individually.
"""

from typing import Any

from abdm_core.observability.flow_logger import log_error, log_phase

from aegle_phr.db import session_scope
from aegle_phr.models import CallbackLog


def dispatch(
    callback_type: str,
    payload: Any,
    request_id: str | None = None,
    correlation_id: str | None = None,
    source_ip: str | None = None,
) -> None:
    """
    Archives one inbound callback and logs it. Never raises.

    Args:
        callback_type: Our short name for the callback ("on_discover",
            "on_init", ...). See the route table in router.py.
        payload: The parsed JSON body. Stored verbatim as JSONB.
        request_id: ABDM's envelope requestId, if the payload had one.
        correlation_id: Our own per-request id, matching the flow_logger
            correlation id on this request's log lines.
        source_ip: Peer address, for spotting traffic that did not come
            from ABDM (informational only -- the real gate is the JWT
            check in abdm_core.callback_auth).
    """
    try:
        log_phase(f"Inbound ABDM callback received: {callback_type}")

        with session_scope() as session:
            session.add(CallbackLog(
                callback_type=callback_type,
                request_id=request_id,
                correlation_id=correlation_id,
                payload=payload,
                source_ip=source_ip,
            ))

        log_phase(f"Callback archived: {callback_type} (requestId={request_id})")

    except Exception as exc:
        # Swallowed on purpose -- see this module's docstring.
        log_error(
            f"Failed to archive inbound callback {callback_type} "
            f"(requestId={request_id}): {type(exc).__name__}: {exc}"
        )
