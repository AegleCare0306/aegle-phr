"""
Local repository for the locker's own HIU tables (aegle_phr/models.py's
LockerPendingRequest, LockerConsentArtefact and LockerHealthInformation).
See those models' docstrings for what each table is for.

Plain functions over session_scope(), dict in / dict out -- same shape as
locker_repository.py's own, so no ORM object ever escapes this module and
callers never deal with detached-instance lifetime.

WHY THIS EXISTS RATHER THAN CALLING repo/ (P20). Until now the locker
raised consents through repo/server/hiu_consent.py and read the results
back out of repo/'s own hiu_consent_repository, hiu_health_information_
repository and two pending-session repositories. That made a PHR app
unable to run without a HIP/HIU backend sitting next to it -- which is
backwards: the locker is its OWN registered ABDM entity (HEALTH_LOCKER +
PHR, its own client id, its own callback URL), so its consent and data
state belongs to it. Nothing here reads or writes a repo/ table.

IDEMPOTENCY LIVES HERE, not in the callers. ABDM redelivers callbacks and
gives no delivery-once guarantee, so upsert_consent_artefact() is keyed on
consent_id and merge_health_information() on transaction_id -- a
redelivered on-fetch or a re-pushed page updates what we hold instead of
duplicating it.
"""

from datetime import datetime, timezone
from typing import Any

from aegle_phr.db import session_scope
from aegle_phr.models import (
    LockerConsentArtefact,
    LockerHealthInformation,
    LockerPendingRequest,
)

# LockerPendingRequest.kind values.
KIND_CONSENT_INIT = "CONSENT_INIT"
KIND_CONSENT_FETCH = "CONSENT_FETCH"
KIND_HI_REQUEST = "HI_REQUEST"

# LockerPendingRequest.state values.
PENDING = "PENDING"
RESOLVED = "RESOLVED"
FAILED = "FAILED"

# LockerConsentArtefact.status values we act on. ABDM owns this vocabulary;
# only GRANTED lets a data request go out.
CONSENT_GRANTED = "GRANTED"
CONSENT_REVOKED = "REVOKED"
CONSENT_EXPIRED = "EXPIRED"


def _pending_as_dict(row: LockerPendingRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "requestId": row.request_id,
        "kind": row.kind,
        "patientId": row.patient_id,
        "hiuId": row.hiu_id,
        "hipId": row.hip_id,
        "consentRequestId": row.consent_request_id,
        "consentId": row.consent_id,
        "transactionId": row.transaction_id,
        "alertEventId": row.alert_event_id,
        "state": row.state,
        "failureReason": row.failure_reason,
        "detail": row.detail,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def _abdm_iso(value: datetime | None) -> str | None:
    """
    ABDM's timestamp form: milliseconds and a literal Z.

    NOT datetime.isoformat(). Python emits microseconds and a "+00:00"
    offset ("2021-09-24T12:41:03.870000+00:00"); ABDM rejects that with
    ABDM-1016 "Invalid Timestamp" -- confirmed live 2026-09-23, when all
    four initial-sync data requests failed 400 on exactly this. An
    artefact's permission window exists to be sent straight back to ABDM
    on a section 7 request, so it is formatted here rather than leaving
    every caller to remember.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _artefact_as_dict(row: LockerConsentArtefact) -> dict[str, Any]:
    return {
        "id": row.id,
        "consentId": row.consent_id,
        "consentRequestId": row.consent_request_id,
        "patientId": row.patient_id,
        "hiuId": row.hiu_id,
        "hipId": row.hip_id,
        "status": row.status,
        "hiTypes": row.hi_types,
        # ABDM-shaped, not Python-shaped -- see _abdm_iso().
        "permissionFrom": _abdm_iso(row.permission_from),
        "permissionTo": _abdm_iso(row.permission_to),
        "dataEraseAt": _abdm_iso(row.data_erase_at),
        "artefact": row.artefact,
        "signature": row.signature,
        "receivedAt": row.received_at.isoformat() if row.received_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def _hi_as_dict(row: LockerHealthInformation) -> dict[str, Any]:
    return {
        "id": row.id,
        "transactionId": row.transaction_id,
        "requestId": row.request_id,
        "consentId": row.consent_id,
        "patientId": row.patient_id,
        "hipId": row.hip_id,
        "pageNumber": row.page_number,
        "pageCount": row.page_count,
        "careContexts": row.care_contexts,
        "status": row.status,
        "failureReason": row.failure_reason,
        "receivedAt": row.received_at.isoformat() if row.received_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


# =============================================================================
# LockerPendingRequest
# =============================================================================

_PENDING_FIELDS = {
    "patient_id", "hiu_id", "hip_id", "consent_request_id", "consent_id",
    "transaction_id", "alert_event_id", "state", "failure_reason", "detail",
}


def create_pending(request_id: str, kind: str, **fields: Any) -> dict[str, Any]:
    """
    Records an outbound call BEFORE it goes out.

    Called from the outbound path only, so a plain insert is right -- a
    duplicate request_id here would mean we generated the same UUID
    twice, which is a bug worth surfacing as an IntegrityError rather
    than silently upserting over.
    """
    if kind not in (KIND_CONSENT_INIT, KIND_CONSENT_FETCH, KIND_HI_REQUEST):
        raise ValueError(f"unknown pending-request kind {kind!r}")
    unknown = set(fields) - _PENDING_FIELDS
    if unknown:
        raise ValueError(f"create_pending got unknown field(s): {sorted(unknown)}")

    with session_scope() as session:
        row = LockerPendingRequest(request_id=request_id, kind=kind, **fields)
        session.add(row)
        session.flush()
        return _pending_as_dict(row)


def get_pending(request_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.query(LockerPendingRequest).filter_by(request_id=request_id).one_or_none()
        return _pending_as_dict(row) if row is not None else None


def update_pending(request_id: str, **fields: Any) -> dict[str, Any] | None:
    """
    Fills in what a callback taught us. Only the fields actually passed are
    written, so a later callback never blanks an earlier one's ids.
    Returns None when no such pending row exists -- an unmatched callback,
    which a caller must treat as a real condition (ABDM talking to us about
    a call we have no record of making), not an error to swallow.
    """
    unknown = set(fields) - _PENDING_FIELDS
    if unknown:
        raise ValueError(f"update_pending got unknown field(s): {sorted(unknown)}")

    with session_scope() as session:
        row = session.query(LockerPendingRequest).filter_by(request_id=request_id).one_or_none()
        if row is None:
            return None
        for key, value in fields.items():
            setattr(row, key, value)
        session.flush()
        return _pending_as_dict(row)


def find_pending_by_transaction(transaction_id: str) -> dict[str, Any] | None:
    """
    The HIP's data push identifies itself by transactionId, not by our own
    REQUEST-ID -- this is how a push gets back to the alert that caused it.
    """
    with session_scope() as session:
        row = (
            session.query(LockerPendingRequest)
            .filter_by(transaction_id=transaction_id)
            .order_by(LockerPendingRequest.id.desc())
            .first()
        )
        return _pending_as_dict(row) if row is not None else None


def pending_hip_bridge_ids() -> list[str]:
    """
    The bridge ids of every data request still awaiting its push.

    Read at startup so a restart mid-transfer does not 401 a HIP's push
    for a request we genuinely made -- the trust set lives in process
    memory, so it has to be rebuilt. Deliberately a pure DB read: startup
    must not depend on ABDM being reachable.
    """
    with session_scope() as session:
        rows = (
            session.query(LockerPendingRequest)
            .filter(LockerPendingRequest.kind == KIND_HI_REQUEST)
            .filter(LockerPendingRequest.state == PENDING)
            .all()
        )
        bridge_ids = set()
        for row in rows:
            detail = row.detail if isinstance(row.detail, dict) else {}
            bridge_id = detail.get("hipBridgeId")
            if isinstance(bridge_id, str) and bridge_id:
                bridge_ids.add(bridge_id)
        return sorted(bridge_ids)


def find_pending_by_consent_request(consent_request_id: str) -> dict[str, Any] | None:
    """
    §6's notify callback names the consentRequestId, which our on-init
    callback wrote onto the CONSENT_INIT row -- this closes that loop.
    """
    with session_scope() as session:
        row = (
            session.query(LockerPendingRequest)
            .filter_by(kind=KIND_CONSENT_INIT, consent_request_id=consent_request_id)
            .order_by(LockerPendingRequest.id.desc())
            .first()
        )
        return _pending_as_dict(row) if row is not None else None


# =============================================================================
# LockerConsentArtefact
# =============================================================================

_ARTEFACT_FIELDS = {
    "consent_request_id", "patient_id", "hiu_id", "hip_id", "status",
    "hi_types", "permission_from", "permission_to", "data_erase_at",
    "artefact", "signature",
}


def upsert_consent_artefact(consent_id: str, **fields: Any) -> dict[str, Any]:
    """
    Stores (or refreshes) one GRANTED artefact, keyed by consent_id so a
    redelivered on-fetch updates rather than duplicates.
    """
    unknown = set(fields) - _ARTEFACT_FIELDS
    if unknown:
        raise ValueError(f"upsert_consent_artefact got unknown field(s): {sorted(unknown)}")

    with session_scope() as session:
        row = session.query(LockerConsentArtefact).filter_by(consent_id=consent_id).one_or_none()
        if row is None:
            row = LockerConsentArtefact(consent_id=consent_id)
            session.add(row)
        for key, value in fields.items():
            setattr(row, key, value)
        session.flush()
        return _artefact_as_dict(row)


def get_consent_artefact(consent_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.query(LockerConsentArtefact).filter_by(consent_id=consent_id).one_or_none()
        return _artefact_as_dict(row) if row is not None else None


def set_consent_status(consent_id: str, status: str) -> dict[str, Any] | None:
    """
    Marks an artefact REVOKED/EXPIRED without discarding it -- the row is
    the record of what we held and when, so it outlives its usefulness.
    """
    with session_scope() as session:
        row = session.query(LockerConsentArtefact).filter_by(consent_id=consent_id).one_or_none()
        if row is None:
            return None
        row.status = status
        session.flush()
        return _artefact_as_dict(row)


def get_artefacts_for_patient(patient_id: str, limit: int = 100) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = (
            session.query(LockerConsentArtefact)
            .filter_by(patient_id=patient_id)
            .order_by(LockerConsentArtefact.received_at.desc())
            .limit(limit)
            .all()
        )
        return [_artefact_as_dict(r) for r in rows]


def find_usable_artefact(patient_id: str, hip_id: str | None, hi_type: str | None) -> dict[str, Any] | None:
    """
    "Do we already hold a GRANTED consent whose window still covers a
    fresh pull?" -- and in practice the honest answer is almost always no.
    Read the next three paragraphs before assuming this is broken.

    WHY IT ALMOST NEVER MATCHES, AND WHY THAT IS CORRECT. ABDM requires a
    consent's permission.dateRange.to to be present-or-past. Tested
    directly, 2026-09-23: a consent init with `to` one year ahead was
    rejected 400, "ABDM-9999: Invalid from/to date and Date must be a
    present/before date". So every consent's data range ENDS AT THE
    INSTANT IT WAS RAISED, which makes permission_to <= now true forever
    after, and means data created later can never fall inside it.

    The consequence is structural, not a defect: a genuinely new record
    ALWAYS needs a new consent. ABDM splits the job deliberately -- the
    SUBSCRIPTION is the standing, ongoing mechanism (it tells us when new
    data exists, via 8.3.11), and a CONSENT is always point-in-time (it
    authorises fetching data that already exists). The locker holds one
    subscription and raises a point-in-time consent per alert. Spec 8.1's
    "use the same consent" cannot be honoured for new data, because ABDM
    does not permit a consent shaped that way.

    REUSE REMAINS POSSIBLE IN ONE CASE, which is why this function is kept
    rather than deleted: a DATA alert for a care context whose records
    PREDATE an existing consent's `to` genuinely does fall inside that
    window. We cannot currently detect that case -- an 8.3.11 alert
    carries a care context reference and an hiType, never the encounter's
    date -- so the conservative default (fall through and raise a fresh
    consent) is the only safe one. If ABDM ever carries a date on the
    alert, this is where that optimisation goes.

    Deliberately narrow: it only ever returns an artefact THIS locker
    fetched for THIS patient, because those are the only rows in this
    table. It can never surface another app's consent -- precisely the
    failure mode the removed discover_self_view_consents() workaround had.
    """
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        query = (
            session.query(LockerConsentArtefact)
            .filter(LockerConsentArtefact.patient_id == patient_id)
            .filter(LockerConsentArtefact.status == CONSENT_GRANTED)
        )
        if hip_id:
            query = query.filter(LockerConsentArtefact.hip_id == hip_id)
        rows = query.order_by(LockerConsentArtefact.received_at.desc()).all()

        for row in rows:
            if row.permission_to is not None and row.permission_to <= now:
                continue
            if hi_type:
                hi_types = row.hi_types or []
                if not isinstance(hi_types, list) or hi_type not in hi_types:
                    continue
            return _artefact_as_dict(row)
        return None


# =============================================================================
# LockerHealthInformation
# =============================================================================

def merge_health_information(
    transaction_id: str,
    *,
    care_contexts: dict[str, Any] | None = None,
    page_number: int | None = None,
    page_count: int | None = None,
    request_id: str | None = None,
    consent_id: str | None = None,
    patient_id: str | None = None,
    hip_id: str | None = None,
    status: str | None = None,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    """
    Merges ONE page of a transfer into this transaction's single row.

    MERGE, NOT OVERWRITE, for care_contexts specifically. A transfer
    arrives as one push per care context; repo/'s equivalent replaced the
    stored record on every page, which was survivable only because the
    reader re-read the whole thing each time. Here each page's entries are
    merged key-by-key, so the row always holds the union of everything
    received -- and the page_number/page_count columns still tell a reader
    whether more is coming (see LockerHealthInformation's own docstring).
    """
    with session_scope() as session:
        row = (
            session.query(LockerHealthInformation)
            .filter_by(transaction_id=transaction_id)
            .one_or_none()
        )
        if row is None:
            row = LockerHealthInformation(transaction_id=transaction_id)
            session.add(row)

        if care_contexts:
            merged = dict(row.care_contexts or {})
            merged.update(care_contexts)
            # Reassigned, not mutated in place: JSONB columns are only
            # marked dirty on assignment, so mutating the existing dict
            # would silently not persist.
            row.care_contexts = merged

        if page_number is not None:
            row.page_number = page_number
        if page_count is not None:
            row.page_count = page_count
        if request_id is not None:
            row.request_id = request_id
        if consent_id is not None:
            row.consent_id = consent_id
        if patient_id is not None:
            row.patient_id = patient_id
        if hip_id is not None:
            row.hip_id = hip_id
        if status is not None:
            row.status = status
        if failure_reason is not None:
            row.failure_reason = failure_reason

        session.flush()
        return _hi_as_dict(row)


def prune_superseded(transaction_id: str) -> dict[str, Any]:
    """
    Drops older copies of any care context this transfer just delivered.

    WHY DUPLICATES EXIST AT ALL. One linked visit produces TWO 8.3.11
    alerts -- a LINK ("a care context was linked") and a DATA ("data is
    available on it"). Each is a separate event id, each is processed
    independently, and because no existing consent can cover new data
    (see find_usable_artefact()), each raises its own consent and makes
    its own data request. Both come back with the same bundle. Confirmed
    live 2026-09-23: ENC9005AHC02 arrived as two transactions three
    seconds apart.

    The read already hides the older copy (get_records_for_patient() takes
    the newest per care context), so this is not about correctness. It is
    about retention: a superseded bundle is still the patient's health
    data, and NO existing trigger would ever clear it -- the consent
    behind it stays perfectly valid, so neither a revoke nor the
    dataEraseAt sweep touches it. Without this it sits there until the
    whole consent lapses.

    SURGICAL, not row-level. An older transfer can carry several care
    contexts (a multi-page transfer covering four visits), and only the
    ones this transfer supersedes are removed -- the rest stay. A transfer
    left with nothing becomes a tombstone, exactly as any other erasure
    does, rather than being deleted outright.
    """
    with session_scope() as session:
        current = (
            session.query(LockerHealthInformation)
            .filter_by(transaction_id=transaction_id)
            .one_or_none()
        )
        if current is None or not isinstance(current.care_contexts, dict):
            return {"prunedFrom": 0, "careContextsPruned": 0}

        fresh = {
            reference for reference, entry in current.care_contexts.items()
            if isinstance(entry, dict) and entry.get("hi_status") == "OK"
        }
        if not fresh:
            return {"prunedFrom": 0, "careContextsPruned": 0}

        older = (
            session.query(LockerHealthInformation)
            .filter(LockerHealthInformation.patient_id == current.patient_id)
            .filter(LockerHealthInformation.transaction_id != transaction_id)
            .filter(LockerHealthInformation.care_contexts.isnot(None))
            .filter(LockerHealthInformation.received_at <= current.received_at)
            .all()
        )

        transfers_touched = 0
        contexts_pruned = 0
        for row in older:
            contexts = row.care_contexts if isinstance(row.care_contexts, dict) else {}
            remaining = {k: v for k, v in contexts.items() if k not in fresh}
            if len(remaining) == len(contexts):
                continue
            contexts_pruned += len(contexts) - len(remaining)
            transfers_touched += 1
            if remaining:
                # Reassigned, not mutated: a JSONB column is only marked
                # dirty on assignment.
                row.care_contexts = remaining
            else:
                row.care_contexts = None
                row.status = ERASED
                row.failure_reason = f"superseded by transfer {transaction_id}"
        session.flush()
        return {"prunedFrom": transfers_touched, "careContextsPruned": contexts_pruned}


def get_health_information(transaction_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = (
            session.query(LockerHealthInformation)
            .filter_by(transaction_id=transaction_id)
            .one_or_none()
        )
        return _hi_as_dict(row) if row is not None else None


def is_transfer_complete(record: dict[str, Any] | None) -> bool:
    """
    Whether every page of a transfer has landed.

    Missing page_number/page_count (a single-page transfer, or an
    older-shaped record) counts as complete -- same fallback the reference
    CLI uses, so the common single-page case is not held open forever.
    """
    if record is None:
        return False
    page_number = record.get("pageNumber")
    page_count = record.get("pageCount")
    if page_number is None or page_count is None:
        return True
    return page_number >= page_count - 1


# =============================================================================
# Retention and erasure
#
# A Health Locker is entitled to HOLD a patient's records for as long as the
# consent behind them is valid -- that is the whole point of a locker, and
# it is why login reads local storage instead of re-requesting from ABDM
# every time. The other half of that entitlement is the obligation: the
# moment the basis for holding the data ends, the data goes.
#
# FOUR TRIGGERS, all of them handled:
#   - consent REVOKED     -- the patient withdrew it (section 6 notify)
#   - consent EXPIRED     -- ABDM said so, or permission_to has passed
#   - dataEraseAt reached -- the erase-by instruction carried in the
#                            artefact itself, which we agreed to when we
#                            raised the consent
#   - patient opts out    -- withdraws the locker relationship entirely
#
# WHAT ERASURE MEANS HERE. The record CONTENT (the decrypted FHIR bundles)
# is destroyed -- set to NULL, not flagged, not moved. What remains is a
# tombstone carrying ids and timestamps: enough to answer "did we hold
# this, and when did we erase it", which is exactly what an auditor or the
# patient is entitled to ask. A tombstone holds no clinical content.
#
# Patient-scoped erasure goes further and strips the care-context
# references too, because "this patient attended that hospital on that
# date" is itself health-adjacent personal data. A patient who has
# withdrawn entirely should not leave that behind.
# =============================================================================

ERASED = "ERASED"


def erase_health_information_for_consent(consent_id: str, reason: str) -> int:
    """
    Destroys every decrypted bundle collected under one consent.

    Returns the number of transfers erased. Idempotent: a transfer whose
    content is already gone is skipped, so re-running after a redelivered
    revoke notification is free.
    """
    with session_scope() as session:
        rows = (
            session.query(LockerHealthInformation)
            .filter(LockerHealthInformation.consent_id == consent_id)
            .all()
        )
        erased = 0
        for row in rows:
            if row.care_contexts is None and row.status == ERASED:
                continue
            row.care_contexts = None
            row.status = ERASED
            row.failure_reason = reason
            erased += 1
        session.flush()
        return erased


def erase_health_information_for_patient(patient_id: str, reason: str) -> int:
    """
    Destroys every decrypted bundle held for one patient, whatever consent
    it arrived under. The opt-out path.
    """
    with session_scope() as session:
        rows = (
            session.query(LockerHealthInformation)
            .filter(LockerHealthInformation.patient_id == patient_id)
            .all()
        )
        erased = 0
        for row in rows:
            if row.care_contexts is None and row.status == ERASED:
                continue
            row.care_contexts = None
            row.status = ERASED
            row.failure_reason = reason
            erased += 1
        session.flush()
        return erased


def redact_artefacts_for_patient(patient_id: str, status: str) -> int:
    """
    Strips the stored consent artefacts of their care-context detail and
    marks them ended.

    The artefact BODY goes because consentDetail.careContexts names the
    specific visits -- health-adjacent personal data in its own right. The
    ids, the window and the status stay: that is the record of what we were
    permitted to hold and until when, which erasure should not destroy.
    """
    with session_scope() as session:
        rows = (
            session.query(LockerConsentArtefact)
            .filter(LockerConsentArtefact.patient_id == patient_id)
            .all()
        )
        for row in rows:
            row.artefact = None
            row.signature = None
            row.status = status
        session.flush()
        return len(rows)


def find_erasable_artefacts(now: datetime | None = None, patient_id: str | None = None) -> list[dict[str, Any]]:
    """
    Artefacts whose retention deadline has passed on the clock alone.

    DRIVEN BY dataEraseAt AND NOTHING ELSE. permission.dateRange.to is NOT
    a retention bound and must never be used as one: it is the end of the
    DATA RANGE the consent covers, and the locker always asks for
    "everything up to now", so it equals the moment the consent was
    raised. Treating it as an expiry erases every record the instant it is
    collected.

    Caught before this shipped, 2026-09-23 -- a first sweep reported 6 of
    6 artefacts erasable, for records we were entitled to hold for another
    full year (dateRange.to 2026-09-23, dataEraseAt 2027-09-23). The two
    fields sit next to each other in the artefact and read alike; they
    mean completely different things.

    Time-based rather than callback-driven on purpose: a consent can lapse
    with no notification at all, and "we kept it because ABDM never
    reminded us" is not a defence.
    """
    now = now or datetime.now(timezone.utc)
    with session_scope() as session:
        query = session.query(LockerConsentArtefact).filter(
            LockerConsentArtefact.data_erase_at.isnot(None),
            LockerConsentArtefact.data_erase_at <= now,
            LockerConsentArtefact.status != CONSENT_EXPIRED,
        )
        if patient_id:
            query = query.filter(LockerConsentArtefact.patient_id == patient_id)
        return [_artefact_as_dict(row) for row in query.all()]


# =============================================================================
# Reading what the locker holds
# =============================================================================

def get_records_for_patient(patient_id: str) -> list[dict[str, Any]]:
    """
    Everything this locker currently holds for one patient, as a flat list
    of care contexts with their decrypted bundle.

    Reads LOCAL STORAGE ONLY -- no ABDM call. That is the payoff of being a
    locker: the records were collected when they became available, so a
    login is a database read, not a round trip per hospital.

    Erased transfers are skipped rather than returned empty: from a
    caller's point of view data we are no longer entitled to hold does not
    exist. Only entries the HIP actually delivered successfully are
    returned; a care context that errored on decrypt is not a record.
    """
    with session_scope() as session:
        rows = (
            session.query(LockerHealthInformation)
            .filter(LockerHealthInformation.patient_id == patient_id)
            .filter(LockerHealthInformation.care_contexts.isnot(None))
            .order_by(LockerHealthInformation.received_at.desc())
            .all()
        )

        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if row.status == ERASED:
                continue
            contexts = row.care_contexts if isinstance(row.care_contexts, dict) else {}
            for reference, entry in contexts.items():
                if not isinstance(entry, dict) or entry.get("hi_status") != "OK":
                    continue
                # Newest transfer wins: the same care context can be
                # delivered more than once (a LINK alert and a DATA alert
                # for one visit, or a re-sync), and the patient should see
                # one copy, the most recent.
                if reference in seen:
                    continue
                seen.add(reference)
                records.append({
                    "careContextReference": reference,
                    "hipId": row.hip_id,
                    "consentId": row.consent_id,
                    "transactionId": row.transaction_id,
                    "receivedAt": row.received_at.isoformat() if row.received_at else None,
                    "bundle": entry.get("bundle"),
                })
        return records
