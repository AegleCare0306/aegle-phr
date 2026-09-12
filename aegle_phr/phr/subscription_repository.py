"""
Local repository for SubscriptionRequest rows (aegle_phr/models.py). See
that model's own docstring for why this table exists.

Plain functions over session_scope(), same shape as call_log.py's own
archive() -- no ORM objects escape this module (dict in, dict out), so
callers never need to think about detached-instance/session lifetime.
"""

from typing import Any

from aegle_phr.db import session_scope
from aegle_phr.models import SubscriptionRequest


def _as_dict(row: SubscriptionRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "requestId": row.request_id,
        "subscriptionRequestId": row.subscription_request_id,
        "subscriptionId": row.subscription_id,
        "patientId": row.patient_id,
        "hiuId": row.hiu_id,
        "status": row.status,
        "detail": row.detail,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def save_new_subscription_request(request_id: str, patient_id: str, hiu_id: str, detail: dict[str, Any]) -> None:
    """Called right after 8.3.2's own init call is made -- one row per attempt, status starts REQUESTED."""
    with session_scope() as session:
        session.add(SubscriptionRequest(
            request_id=request_id,
            patient_id=patient_id,
            hiu_id=hiu_id,
            status="REQUESTED",
            detail=detail,
        ))


def link_subscription_request_id(request_id: str, subscription_request_id: str, detail: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """
    Called from subscription_on_init (8.3.3) once ABDM's own
    subscriptionRequest.id is known. Returns the updated row as a dict, or
    None if request_id has no matching row (nothing to correlate against).
    """
    with session_scope() as session:
        row = session.query(SubscriptionRequest).filter_by(request_id=request_id).one_or_none()
        if row is None:
            return None
        row.subscription_request_id = subscription_request_id
        if detail is not None:
            row.detail = detail
        session.flush()
        return _as_dict(row)


def get_by_request_id(request_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.query(SubscriptionRequest).filter_by(request_id=request_id).one_or_none()
        return _as_dict(row) if row is not None else None


def get_by_subscription_request_id(subscription_request_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.query(SubscriptionRequest).filter_by(subscription_request_id=subscription_request_id).one_or_none()
        return _as_dict(row) if row is not None else None


def update_status_by_subscription_request_id(
    subscription_request_id: str,
    status: str,
    subscription_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Called from subscription_notify (8.3.5/8.3.8/8.3.10) once ABDM
    decides. Returns the updated row as a dict, or None if
    subscription_request_id has no matching row.
    """
    with session_scope() as session:
        row = session.query(SubscriptionRequest).filter_by(subscription_request_id=subscription_request_id).one_or_none()
        if row is None:
            return None
        row.status = status
        if subscription_id is not None:
            row.subscription_id = subscription_id
        if detail is not None:
            row.detail = detail
        session.flush()
        return _as_dict(row)


def get_all_for_patient(patient_id: str) -> list[dict[str, Any]]:
    """Debugging/UI helper -- every locally-known subscription attempt for one patient, newest first."""
    with session_scope() as session:
        rows = (
            session.query(SubscriptionRequest)
            .filter_by(patient_id=patient_id)
            .order_by(SubscriptionRequest.created_at.desc())
            .all()
        )
        return [_as_dict(row) for row in rows]
