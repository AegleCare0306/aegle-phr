"""
Local repository for the Health Locker tables (aegle_phr/models.py's own
PatientLocker and LockerAlert). See those models' docstrings for what each
table is for.

Plain functions over session_scope(), dict in / dict out -- same shape as
subscription_repository.py's own, so no ORM object ever escapes this module
and callers never deal with detached-instance lifetime.

IDEMPOTENCY LIVES HERE, not in the callers. upsert_patient_locker() is
keyed on (patient_id, locker_id) and record_alert_if_new() on event_id, so
"ensure on login" and a redelivered ABDM alert are both safe to run twice.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert

from aegle_phr.db import session_scope
from aegle_phr.models import LockerAlert, PatientLocker

# opt_in_state values. Only ALLOWED lets the automation act -- see
# PatientLocker's own docstring for why a patient's own choice has to
# outrank what ABDM would otherwise happily let us do.
OPT_IN_PENDING = "PENDING"
OPT_IN_ALLOWED = "ALLOWED"
OPT_IN_DECLINED = "DECLINED"
OPT_IN_OPTED_OUT = "OPTED_OUT"

# processing_state values for LockerAlert.
ALERT_RECEIVED = "RECEIVED"
ALERT_CONSENT_REQUESTED = "CONSENT_REQUESTED"
ALERT_CONSENT_GRANTED = "CONSENT_GRANTED"
ALERT_DATA_REQUESTED = "DATA_REQUESTED"
ALERT_DATA_RECEIVED = "DATA_RECEIVED"
ALERT_FAILED = "FAILED"

# initial_sync_state values.
SYNC_NOT_STARTED = "NOT_STARTED"
SYNC_RUNNING = "RUNNING"
SYNC_DONE = "DONE"
SYNC_FAILED = "FAILED"


def _locker_as_dict(row: PatientLocker) -> dict[str, Any]:
    return {
        "id": row.id,
        "patientId": row.patient_id,
        "lockerId": row.locker_id,
        "subscriptionId": row.subscription_id,
        "consentAutoApprovalId": row.consent_auto_approval_id,
        "subscriptionRequestId": row.subscription_request_id,
        "status": row.status,
        "categories": row.categories,
        "periodFrom": row.period_from.isoformat() if row.period_from else None,
        "periodTo": row.period_to.isoformat() if row.period_to else None,
        "optInState": row.opt_in_state,
        "optInDecidedAt": row.opt_in_decided_at.isoformat() if row.opt_in_decided_at else None,
        "initialSyncState": row.initial_sync_state,
        "initialSyncDetail": row.initial_sync_detail,
        "detail": row.detail,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def _alert_as_dict(row: LockerAlert) -> dict[str, Any]:
    return {
        "id": row.id,
        "eventId": row.event_id,
        "subscriptionId": row.subscription_id,
        "patientId": row.patient_id,
        "lockerId": row.locker_id,
        "category": row.category,
        "hipId": row.hip_id,
        "contexts": row.contexts,
        "processingState": row.processing_state,
        "failureReason": row.failure_reason,
        "consentRequestId": row.consent_request_id,
        "consentId": row.consent_id,
        "healthInformationRequestId": row.health_information_request_id,
        "detail": row.detail,
        "receivedAt": row.received_at.isoformat() if row.received_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


# =============================================================================
# PatientLocker
# =============================================================================

def get_patient_locker(patient_id: str, locker_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = (
            session.query(PatientLocker)
            .filter_by(patient_id=patient_id, locker_id=locker_id)
            .one_or_none()
        )
        return _locker_as_dict(row) if row is not None else None


def upsert_patient_locker(patient_id: str, locker_id: str, **fields: Any) -> dict[str, Any]:
    """
    Creates or updates the single (patient, locker) row.

    Only the fields actually passed are written -- a caller refreshing the
    subscription status from 8.3.17 must not blank out opt_in_state or the
    initial-sync progress it knows nothing about. That is why this takes
    **fields rather than a full row.
    """
    allowed = {
        "subscription_id", "consent_auto_approval_id", "subscription_request_id",
        "status", "categories", "period_from", "period_to",
        "opt_in_state", "opt_in_decided_at",
        "initial_sync_state", "initial_sync_detail", "detail",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"upsert_patient_locker got unknown field(s): {sorted(unknown)}")

    with session_scope() as session:
        row = (
            session.query(PatientLocker)
            .filter_by(patient_id=patient_id, locker_id=locker_id)
            .one_or_none()
        )
        if row is None:
            row = PatientLocker(patient_id=patient_id, locker_id=locker_id)
            session.add(row)
        for key, value in fields.items():
            setattr(row, key, value)
        session.flush()
        return _locker_as_dict(row)


def set_opt_in(patient_id: str, locker_id: str, state: str) -> dict[str, Any]:
    """Records the patient's own decision, with the timestamp it was made."""
    if state not in (OPT_IN_PENDING, OPT_IN_ALLOWED, OPT_IN_DECLINED, OPT_IN_OPTED_OUT):
        raise ValueError(f"unknown opt-in state {state!r}")
    return upsert_patient_locker(
        patient_id,
        locker_id,
        opt_in_state=state,
        opt_in_decided_at=datetime.now(timezone.utc),
    )


def get_lockers_for_patient(patient_id: str) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.query(PatientLocker).filter_by(patient_id=patient_id).all()
        return [_locker_as_dict(r) for r in rows]


# =============================================================================
# LockerAlert
# =============================================================================

def record_alert_if_new(
    event_id: str,
    patient_id: str,
    *,
    subscription_id: str | None = None,
    locker_id: str | None = None,
    category: str | None = None,
    hip_id: str | None = None,
    contexts: Any = None,
    detail: Any = None,
) -> tuple[dict[str, Any], bool]:
    """
    Records an 8.3.11 alert, keyed by ABDM's own event.id.

    Returns (row, is_new). is_new is False for a REDELIVERY -- the caller
    still acknowledges it (ABDM asked, and a redelivery means our previous
    ack did not land) but must NOT process it a second time into a
    duplicate consent request. The insert is an ON CONFLICT DO NOTHING so
    two concurrent deliveries of the same event cannot both win.

    is_new comes from RETURNING, NOT from rowcount. Measured on this
    stack (psycopg3): an ON CONFLICT DO NOTHING insert reports
    rowcount == -1 whether or not it actually inserted, so testing
    rowcount silently reported every alert -- including genuinely new
    ones -- as a redelivery, and nothing would ever have been processed.
    RETURNING yields exactly one row when the insert happened and none
    when the conflict fired, which is the real signal.
    """
    with session_scope() as session:
        stmt = (
            pg_insert(LockerAlert)
            .values(
                event_id=event_id,
                patient_id=patient_id,
                subscription_id=subscription_id,
                locker_id=locker_id,
                category=category,
                hip_id=hip_id,
                contexts=contexts,
                detail=detail,
                processing_state=ALERT_RECEIVED,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
            .returning(LockerAlert.id)
        )
        inserted_id = session.execute(stmt).scalar_one_or_none()
        is_new = inserted_id is not None
        session.flush()

        row = session.query(LockerAlert).filter_by(event_id=event_id).one()
        return _alert_as_dict(row), is_new


def update_alert_state(
    event_id: str,
    state: str,
    *,
    failure_reason: str | None = None,
    consent_request_id: str | None = None,
    consent_id: str | None = None,
    health_information_request_id: str | None = None,
) -> dict[str, Any] | None:
    """
    Advances one alert's processing state. Only the ids actually supplied
    are written, so a later step never blanks an earlier step's id.

    failure_reason is the ONE exception to that rule: it belongs to the
    FAILED state, so advancing to any other state clears it. Without this
    a recovered alert keeps its old failure text forever -- observed live
    2026-09-23, when four alerts that had failed ABDM-1016 and then
    succeeded on retry still read "health information request returned
    400" while sitting in DATA_REQUESTED. Harmless to the flow, actively
    misleading to anyone diagnosing it.
    """
    with session_scope() as session:
        row = session.query(LockerAlert).filter_by(event_id=event_id).one_or_none()
        if row is None:
            return None
        row.processing_state = state
        if failure_reason is not None:
            row.failure_reason = failure_reason
        elif state != ALERT_FAILED:
            row.failure_reason = None
        if consent_request_id is not None:
            row.consent_request_id = consent_request_id
        if consent_id is not None:
            row.consent_id = consent_id
        if health_information_request_id is not None:
            row.health_information_request_id = health_information_request_id
        session.flush()
        return _alert_as_dict(row)


def redact_alert_contexts_for_patient(patient_id: str) -> int:
    """
    Strips the care-context detail from a patient's alert log, leaving the
    processing history intact.

    Used by the opt-out path (see aegle_phr/phr/retention.py). An alert's
    `contexts` names the specific visits that became available -- "this
    person attended that hospital on that date" is health-adjacent
    personal data even with no clinical content attached, so it goes when
    a patient withdraws. The state machine, ids and timestamps stay: they
    are how we can answer what happened and when, and they say nothing
    about the patient's health.
    """
    with session_scope() as session:
        rows = session.query(LockerAlert).filter_by(patient_id=patient_id).all()
        for row in rows:
            row.contexts = None
            row.detail = None
        session.flush()
        return len(rows)


def get_alert(event_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.query(LockerAlert).filter_by(event_id=event_id).one_or_none()
        return _alert_as_dict(row) if row is not None else None


def get_alerts_for_patient(patient_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = (
            session.query(LockerAlert)
            .filter_by(patient_id=patient_id)
            .order_by(LockerAlert.received_at.desc())
            .limit(limit)
            .all()
        )
        return [_alert_as_dict(r) for r in rows]


def find_granted_consent_for(patient_id: str, hip_id: str | None, hi_type: str | None) -> dict[str, Any] | None:
    """
    The DATA-alert path's "reuse an existing GRANTED locker-raised consent
    before raising a new one" lookup (P19 section 3.5).

    Deliberately narrow: it only ever returns a consent THIS locker raised
    for THIS patient, because those are the only rows in this table. It can
    never surface another app's consent -- which is precisely the failure
    mode the removed discover_self_view_consents() workaround had.
    """
    with session_scope() as session:
        query = (
            session.query(LockerAlert)
            .filter(LockerAlert.patient_id == patient_id)
            .filter(LockerAlert.consent_id.isnot(None))
            .filter(LockerAlert.processing_state.in_(
                [ALERT_CONSENT_GRANTED, ALERT_DATA_REQUESTED, ALERT_DATA_RECEIVED]
            ))
        )
        if hip_id:
            query = query.filter(LockerAlert.hip_id == hip_id)
        rows = query.order_by(LockerAlert.received_at.desc()).all()

        if hi_type:
            for row in rows:
                contexts = row.contexts or []
                if not isinstance(contexts, list):
                    continue
                # An alert's hiType can be a COMMA-JOINED list of several
                # HI types, not one value -- confirmed live 2026-09-23,
                # see locker_service.hi_types_from_contexts(). An exact
                # == comparison would miss every multi-type alert and
                # wrongly raise a duplicate consent for one we already
                # hold.
                for c in contexts:
                    if not isinstance(c, dict) or not isinstance(c.get("hiType"), str):
                        continue
                    if hi_type in {part.strip() for part in c["hiType"].split(",")}:
                        return _alert_as_dict(row)
            return None

        return _alert_as_dict(rows[0]) if rows else None
