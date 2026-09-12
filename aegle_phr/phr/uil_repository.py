"""
Local repository for UilLinkRequest rows (aegle_phr/models.py). See that
model's own docstring for why one row exists per outbound call rather than
one row per overall linking journey.

Plain functions over session_scope(), same shape as subscription_repository.py
-- no ORM objects escape this module (dict in, dict out).
"""

from typing import Any

from aegle_phr.db import session_scope
from aegle_phr.models import UilLinkRequest


def _as_dict(row: UilLinkRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "requestId": row.request_id,
        "stage": row.stage,
        "hipId": row.hip_id,
        "abhaAddress": row.abha_address,
        "status": row.status,
        "detail": row.detail,
        "linkRefNumber": row.link_ref_number,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def save_new_request(request_id: str, stage: str, hip_id: str, abha_address: str, detail: dict[str, Any] | None = None) -> None:
    """Called right before EACH of the three outbound calls is made -- one row per call, status starts PENDING."""
    with session_scope() as session:
        session.add(UilLinkRequest(
            request_id=request_id,
            stage=stage,
            hip_id=hip_id,
            abha_address=abha_address,
            status="PENDING",
            detail=detail,
        ))


def get_by_request_id(request_id: str) -> dict[str, Any] | None:
    """The one read the frontend's poll route needs."""
    with session_scope() as session:
        row = session.query(UilLinkRequest).filter_by(request_id=request_id).one_or_none()
        return _as_dict(row) if row is not None else None


def update_by_request_id(
    request_id: str,
    status: str,
    detail: dict[str, Any] | None = None,
    link_ref_number: str | None = None,
) -> dict[str, Any] | None:
    """
    Called from uil_services.py's three handle_on_*() functions once the
    matching callback arrives. Returns the updated row as a dict, or None
    if request_id has no matching row (nothing to correlate against --
    logged as an error by the caller, same convention as
    subscription_repository.py's own update functions).
    """
    with session_scope() as session:
        row = session.query(UilLinkRequest).filter_by(request_id=request_id).one_or_none()
        if row is None:
            return None
        row.status = status
        if detail is not None:
            row.detail = detail
        if link_ref_number is not None:
            row.link_ref_number = link_ref_number
        session.flush()
        return _as_dict(row)


def get_all_for_journey(hip_id: str, abha_address: str) -> list[dict[str, Any]]:
    """Debugging/UI helper -- every locally-known UIL row for one hip+abhaAddress pair, newest first (across all three stages)."""
    with session_scope() as session:
        rows = (
            session.query(UilLinkRequest)
            .filter_by(hip_id=hip_id, abha_address=abha_address)
            .order_by(UilLinkRequest.created_at.desc())
            .all()
        )
        return [_as_dict(row) for row in rows]
