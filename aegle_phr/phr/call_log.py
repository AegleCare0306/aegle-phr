"""
Writes one abdm_call_log row per outbound ABDM call.

Never raises: losing an archive row must not fail the ABDM call it is
observing. A failure here is logged and swallowed, same contract as the
inbound callback dispatcher.
"""

from typing import Any

from abdm_core.observability.flow_logger import log_error

from aegle_phr.db import session_scope
from aegle_phr.models import AbdmCallLog
from aegle_phr.phr.redaction import redact


def archive(
    route: str,
    abdm_url: str,
    request_body: Any,
    response_status: int | None,
    response_body: Any,
    duration_ms: int,
    error: str | None = None,
    plaintext_secrets: tuple[str, ...] = (),
) -> None:
    """
    Args:
        plaintext_secrets: The plaintext mobile/OTP/password handled during
            this call. Scrubbed by exact match from BOTH bodies before
            anything is written -- see aegle_phr.phr.redaction.
    """
    try:
        with session_scope() as session:
            session.add(AbdmCallLog(
                route=route,
                abdm_url=abdm_url,
                request_body=redact(request_body, plaintext_secrets),
                response_status=response_status,
                response_body=redact(response_body, plaintext_secrets),
                duration_ms=duration_ms,
                error=error,
            ))
    except Exception as exc:
        log_error(f"abdm_call_log archive failed for {route}: {type(exc).__name__}: {exc}")
