"""
Local repository for ProfileShareRequest rows (aegle_phr/models.py). See
that model's own docstring for why `source` exists and why `token_expiry`
is Text.

Plain functions over session_scope(), same shape as uil_repository.py and
subscription_repository.py -- no ORM objects escape this module (dict in,
dict out).
"""

from typing import Any

from aegle_phr.db import session_scope
from aegle_phr.models import ProfileShareRequest


def _as_dict(row: ProfileShareRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "requestId": row.request_id,
        "hipId": row.hip_id,
        "counterId": row.counter_id,
        "abhaAddress": row.abha_address,
        "status": row.status,
        "tokenNumber": row.token_number,
        "tokenExpiry": row.token_expiry,
        "detail": row.detail,
        "source": row.source,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def save_new_share(
    request_id: str,
    hip_id: str,
    counter_id: str,
    abha_address: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """
    Called right BEFORE the outbound share call goes out -- status starts
    PENDING.

    The ordering is deliberate and is the same reason uil_repository.py's
    own save_new_request() is called where it is: an inbound callback can
    genuinely arrive before our own outbound HTTP response does, and a row
    that does not exist yet is a row the callback cannot correlate to.
    """
    with session_scope() as session:
        session.add(ProfileShareRequest(
            request_id=request_id,
            hip_id=hip_id,
            counter_id=counter_id,
            abha_address=abha_address,
            status="PENDING",
            detail=detail,
        ))


def get_by_request_id(request_id: str) -> dict[str, Any] | None:
    """The one read the frontend's poll route needs."""
    with session_scope() as session:
        row = session.query(ProfileShareRequest).filter_by(request_id=request_id).one_or_none()
        return _as_dict(row) if row is not None else None


def update_by_request_id(
    request_id: str,
    status: str,
    detail: dict[str, Any] | None = None,
    token_number: str | None = None,
    token_expiry: str | None = None,
    source: str | None = None,
) -> dict[str, Any] | None:
    """
    Called from the share route once ABDM answers, and again from
    profile_share_services.py if a callback arrives.

    Returns the updated row, or None when request_id matches nothing --
    the caller logs that as an error rather than this module raising, same
    convention as uil_repository.py's own update function.
    """
    with session_scope() as session:
        row = session.query(ProfileShareRequest).filter_by(request_id=request_id).one_or_none()
        if row is None:
            return None
        row.status = status
        if detail is not None:
            row.detail = detail
        if token_number is not None:
            row.token_number = token_number
        if token_expiry is not None:
            row.token_expiry = token_expiry
        if source is not None:
            row.source = source
        session.flush()
        return _as_dict(row)


def find_latest_pending(abha_address: str, counter_id: str | None = None) -> dict[str, Any] | None:
    """
    CANDIDATE A'S FALLBACK CORRELATION, and the reason this function is
    not just a nicety.

    An on-share callback is SUPPOSED to carry response.requestId, the way
    every other callback in this project does. But this payload's envelope
    has never been seen -- no sample exists anywhere -- so it may well
    arrive with no correlation id at all. Without a fallback, a callback
    that DOES carry a token would be archived and then dropped on the
    floor, and we would wrongly conclude Candidate A does not exist.

    Matches the newest row for this patient that has not yet got a token,
    optionally narrowed to one counter. Deliberately looser than an id
    match, and deliberately only used when the id match has already failed
    -- see profile_share_services.py.
    """
    with session_scope() as session:
        query = (
            session.query(ProfileShareRequest)
            .filter(ProfileShareRequest.abha_address == abha_address)
            .filter(ProfileShareRequest.status.in_(("PENDING", "SHARED")))
        )
        if counter_id:
            query = query.filter(ProfileShareRequest.counter_id == counter_id)
        row = query.order_by(ProfileShareRequest.created_at.desc()).first()
        return _as_dict(row) if row is not None else None


def list_recent(abha_address: str, limit: int = 20) -> list[dict[str, Any]]:
    """Debugging/UI helper -- this patient's recent shares, newest first."""
    with session_scope() as session:
        rows = (
            session.query(ProfileShareRequest)
            .filter_by(abha_address=abha_address)
            .order_by(ProfileShareRequest.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_as_dict(row) for row in rows]
