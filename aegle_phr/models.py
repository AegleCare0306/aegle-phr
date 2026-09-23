"""
SQLAlchemy 2.0 declarative models for the PHR app.

Class definitions only -- no engine, no connection, no metadata.create_all()
here. Schema changes go through Alembic (alembic/versions/), never through
create_all(); the two must not both own the schema.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for every PHR table."""


class CallbackLog(Base):
    """
    Raw archive of every inbound ABDM callback this app accepts.

    The PHR equivalent of the existing backend's storage/callbacks/*.json
    files -- but in Postgres from day one rather than a .jsonl file store,
    which is a known standing caveat over there.

    Deliberately dumb: it records what arrived, verbatim, with no
    interpretation. Per-callback handling lands in P3 and will read from
    here rather than replacing it -- an unparseable or unexpected payload
    must still be captured, not dropped.
    """

    __tablename__ = "callback_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Our own short name for the callback (e.g. "on_discover"), not an
    # ABDM field -- see aegle_phr/callbacks/router.py's route table.
    callback_type: Mapped[str] = mapped_column(Text, nullable=False)

    # ABDM's own envelope requestId. Nullable because a malformed payload
    # that lacks it must still be archived rather than rejected.
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Our per-request id, shared with abdm_core's flow_logger so a log line
    # and its archived payload can be tied together.
    correlation_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    source_ip: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_callback_log_received_at", "received_at"),
        Index("ix_callback_log_request_id", "request_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<CallbackLog id={self.id} type={self.callback_type!r} "
            f"request_id={self.request_id!r} received_at={self.received_at!r}>"
        )


class AbdmCallLog(Base):
    """
    Archive of every OUTBOUND call this app makes to ABDM.

    Exists because ABDM's own specification leaves the "Response Body"
    section EMPTY for /enrollment/verify, /enrollment/suggestion and
    /enrollment/enrol. This table is how the real shapes get recovered
    after a live sandbox run -- so it stores bodies verbatim rather than
    parsing them into anything.

    REDACTION: plaintext mobile numbers, OTP values and passwords reach
    this backend from the UI but must NEVER land here. Everything written
    to request_body/response_body goes through
    aegle_phr.phr.redaction.redact() first. The RSA-encrypted forms of
    those same values are opaque and ARE stored -- they are what was
    actually put on the wire, and they are what a failed decrypt needs to
    be diagnosed against.
    """

    __tablename__ = "abdm_call_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Our own route that triggered this call (e.g. "/phr/enrollment/request-otp").
    route: Mapped[str] = mapped_column(Text, nullable=False)

    abdm_url: Mapped[str] = mapped_column(Text, nullable=False)

    # JSONB rather than text: these get queried into when recovering the
    # undocumented shapes (e.g. request_body->>'txnId' to follow one run).
    # Nullable because a GET has no body.
    request_body: Mapped[Any | None] = mapped_column(JSONB, nullable=True)

    # Null when nothing answered (connection error/timeout) -- see `error`.
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Holds whatever came back, including a bare `true` (the isExists
    # endpoint returns a scalar, not an object) or a JSON string for a
    # non-JSON body. JSONB accepts all of those.
    response_body: Mapped[Any | None] = mapped_column(JSONB, nullable=True)

    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # Not in the original column list, but a row for a call that never got
    # a response would otherwise carry no information at all.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_abdm_call_log_called_at", "called_at"),
        Index("ix_abdm_call_log_route", "route"),
    )

    def __repr__(self) -> str:
        return (
            f"<AbdmCallLog id={self.id} route={self.route!r} "
            f"status={self.response_status!r} duration_ms={self.duration_ms!r}>"
        )


class SubscriptionRequest(Base):
    """
    P13 -- local tracking for spec §8's Subscription Flow, one row per
    subscription request this app has ever initiated or been notified
    about.

    WHY THIS TABLE EXISTS: unlike consent (repo/'s own file-backed
    hiu_consent_repository, outside this app entirely), aegle_phr has no
    prior local state for anything subscription-shaped. This is needed
    for three things:
      1. subscription_on_init (8.3.3) correlates ABDM's callback back to
         the request WE initiated via our own REQUEST-ID header value
         (request_id below) -- mirrors repo/server/callbacks/repository/
         pending_consent_request_repository.py's shape, in Postgres
         instead of a .jsonl file, matching this app's own established
         persistence (see CallbackLog/AbdmCallLog above).
      2. subscription_notify (8.3.5/8.3.8/8.3.10) updates status/
         subscription_id once ABDM decides (GRANTED/DENIED/REVOKE),
         looked up by subscription_request_id (ABDM's own id, learned
         from the on-init callback).
      3. The Subscriptions UI (P13 item 3) lists current subscriptions
         without needing a live ABDM round trip for every render.

    request_id is UNIQUE (one row per initiate call) -- subscription_id is
    nullable until GRANTED (a DENIED request never gets one).
    """

    __tablename__ = "subscription_request"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Our own REQUEST-ID header value from the 8.3.2 init call -- what
    # ABDM's 8.3.3 callback echoes back as response.requestId, and how we
    # correlate it back to this row.
    request_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    # ABDM's own subscriptionRequest.id, learned from the 8.3.3 callback.
    # Null until that callback arrives.
    subscription_request_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ABDM's own subscription.id, learned once GRANTED (8.3.5's own notify
    # body, or a later 8.3.13/8.3.14 lookup). Null until granted.
    subscription_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    hiu_id: Mapped[str] = mapped_column(Text, nullable=False)

    # Our own tracking, not an ABDM field -- starts "REQUESTED", updated by
    # subscription_notify to whatever status value actually arrives
    # (GRANTED/DENIED/REVOKE per the spec's own inconsistent enum -- see
    # subscription_services.py's own docstring).
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="REQUESTED")

    # Whatever we last learned about this subscription (init request body,
    # on-init callback, notify callback) -- stored verbatim, not parsed
    # into columns, same "record what arrived" discipline as CallbackLog.
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_subscription_request_subscription_request_id", "subscription_request_id"),
        Index("ix_subscription_request_patient_id", "patient_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<SubscriptionRequest id={self.id} request_id={self.request_id!r} "
            f"subscription_request_id={self.subscription_request_id!r} "
            f"status={self.status!r}>"
        )


class UilLinkRequest(Base):
    """
    P15 -- local tracking for spec §10's User-Initiated Linking, one row
    per OUTBOUND CALL (not per overall linking journey): discover,
    link-init and link-confirm each get their own row, because each is a
    genuinely separate async round trip with its own freshly-generated
    REQUEST-ID and its own inbound callback -- unlike SubscriptionRequest
    above (one initiate call, then a SEPARATE id -- subscriptionRequestId
    -- carries every later update), nothing about UIL hands back a stable
    id that could anchor one row across all three stages. `stage` is what
    lets three rows for the same logical journey (same hip_id +
    abha_address) be told apart.

    WHY THIS TABLE EXISTS: mirrors SubscriptionRequest's own reasoning --
    1. Each of the three inbound callbacks (on-discover/on-init/on-confirm,
       aegle_phr/callbacks/uil_services.py) correlates back to the row THIS
       app created right before making the matching outbound call, via
       response.requestId equalling request_id below.
    2. The frontend has no websocket/push, so it polls GET /phr/uil/result
       (reads this table by request_id) for a bounded window after each
       outbound call -- this table IS the mechanism that makes that
       possible, same role CallbackLog would play if it were queryable by
       request_id per-flow instead of being a flat, uninterpreted archive.
    3. link_ref_number is populated here the moment the link-init stage's
       own on-init callback arrives (its own row, stage="link_init") --
       needed to build the link-confirm call's own body. The frontend also
       carries this value forward in its own React state (from the same
       poll response), so this column is not the only copy -- but keeping
       it here too matches this project's own "stash what we learned"
       discipline (CallbackLog/AbdmCallLog/SubscriptionRequest.detail) and
       makes a mid-flow row inspectable on its own, without needing to
       replay the frontend's state.

    request_id is UNIQUE (one row per outbound call, never reused/updated
    to a different value the way updating-in-place would require) --
    status starts "PENDING", moves to "GRANTED"/"DENIED"/"ERROR"/"TIMEOUT"
    (our own tracking words, not a literal ABDM enum -- discover/init/
    confirm don't share one status vocabulary, so this stays a plain
    label rather than a borrowed one that would only be half-accurate on
    two of the three stages).
    """

    __tablename__ = "uil_link_request"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Our own REQUEST-ID header value for the ONE outbound call this row
    # tracks -- what the matching inbound callback echoes back as
    # response.requestId, and how we correlate it back to this row.
    request_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    # "discover" | "link_init" | "link_confirm" -- which of the three UIL
    # outbound calls this row is for. Not an ABDM field, our own label.
    stage: Mapped[str] = mapped_column(Text, nullable=False)

    hip_id: Mapped[str] = mapped_column(Text, nullable=False)
    abha_address: Mapped[str] = mapped_column(Text, nullable=False)

    # Our own tracking, not an ABDM field. Starts "PENDING", updated once
    # the matching callback arrives (or the poll window times out --
    # see uil_repository.py's own mark_timed_out()).
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")

    # Whatever we last learned about this specific call (the outbound
    # request body we sent, then overwritten with the inbound callback
    # body once it arrives) -- stored verbatim, not parsed into columns,
    # same "record what arrived" discipline as CallbackLog.
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Populated only on the "link_init" stage's own row, once its on-init
    # callback arrives (link.referenceNumber) -- see this class's own
    # docstring, point 3.
    link_ref_number: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_uil_link_request_hip_abha", "hip_id", "abha_address"),
    )

    def __repr__(self) -> str:
        return (
            f"<UilLinkRequest id={self.id} request_id={self.request_id!r} "
            f"stage={self.stage!r} status={self.status!r}>"
        )


class PatientLocker(Base):
    """
    P19 -- one row per (patient, locker): what Setup Locker created for
    them, and what the patient themselves decided about it.

    WHY THIS IS SEPARATE FROM SubscriptionRequest ABOVE: that table tracks
    a subscription this app INITIATED via 8.3.2 and then correlated through
    on-init -> notify. The locker path has no such round trip. Setup Locker
    (8.3.18) returns BOTH ids synchronously and the subscription is already
    GRANTED -- confirmed live 2026-09-22 for poojaanchaliya@sbx, granted
    57 ms after creation with no approve step. Forcing that into
    SubscriptionRequest's request_id-keyed shape would mean inventing a
    request_id that never existed on the wire.

    opt_in_state is the patient's own decision, and it is the reason this
    table is not derivable from ABDM alone: a patient who paused, revoked
    or removed the locker must NOT be silently re-subscribed on next login
    (P19 section 3.5). ABDM would happily let us call Setup Locker again;
    this column is what stops us doing it behind their back.

    initial_sync_state tracks the one-off backfill of care contexts linked
    BEFORE the subscription existed -- alerts only cover what is linked
    after, so without this a patient's existing records never appear. Kept
    here rather than in LockerAlert because it is per-patient, not per-event.
    """

    __tablename__ = "patient_locker"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    patient_id: Mapped[str] = mapped_column(Text, nullable=False)

    # Our own locker's service id (settings.abdm_health_locker_id). Stored
    # per row rather than assumed, so a future second locker -- or a
    # patient carrying rows from before a locker id change -- stays
    # unambiguous, and so every query can filter on it explicitly.
    locker_id: Mapped[str] = mapped_column(Text, nullable=False)

    # Both ids returned by Setup Locker (8.3.18). The spec documents only
    # consent_auto_approval_id; subscription_id came back too on the real
    # call, which is how we know one Setup Locker creates both artefacts.
    subscription_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_auto_approval_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Only set when the subscription came from the 8.3.2 init recovery
    # route rather than Setup Locker -- null for the normal path.
    subscription_request_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ABDM's own subscription status, stored as it arrives. Compare
    # case-insensitively: 8.3.17 returns "Granted" where 8.3.14 and 8.3.15
    # return "GRANTED" for the very same subscription (confirmed live).
    status: Mapped[str | None] = mapped_column(Text, nullable=True)

    categories: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    period_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # "PENDING" (never asked), "ALLOWED", "DECLINED" (said Not now),
    # "OPTED_OUT" (paused/revoked/removed after having allowed). Only
    # ALLOWED lets the automation act; anything else means ask again
    # through the opt-in screen rather than calling Setup Locker.
    opt_in_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    opt_in_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # "NOT_STARTED" / "RUNNING" / "DONE" / "FAILED" -- see this class's
    # own docstring for why the initial sync exists at all.
    initial_sync_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="NOT_STARTED")
    initial_sync_detail: Mapped[Any | None] = mapped_column(JSONB, nullable=True)

    # Whatever we last read back from 8.3.16/8.3.17/8.3.18, verbatim --
    # same "record what arrived" discipline as CallbackLog.
    detail: Mapped[Any | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("uq_patient_locker_patient_locker", "patient_id", "locker_id", unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"<PatientLocker id={self.id} patient_id={self.patient_id!r} "
            f"locker_id={self.locker_id!r} opt_in={self.opt_in_state!r} status={self.status!r}>"
        )


class LockerAlert(Base):
    """
    P19 -- one row per 8.3.11 LINK/DATA alert, keyed by ABDM's own event.id.

    TWO JOBS. First, idempotency: ABDM redelivers an alert it thinks went
    unacknowledged, and the spec gives no delivery-once guarantee. event_id
    is UNIQUE, so a redelivered alert is acknowledged again (cheap, and
    what ABDM wants) but never processed twice into a duplicate consent
    request. Second, diagnosability: the LINK path spans an alert, a
    consent request, an auto-approval we do not control, a fetch and a
    data push, each able to fail independently and none of them
    synchronous. processing_state plus failure_reason is what makes a
    stalled record explainable instead of just absent.

    processing_state moves RECEIVED -> CONSENT_REQUESTED -> CONSENT_GRANTED
    -> DATA_REQUESTED -> DATA_RECEIVED, or FAILED with failure_reason set.
    Failures are recorded, never swallowed (P19 section 3.5).
    """

    __tablename__ = "locker_alert"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # ABDM's own event.id -- the dedupe key.
    event_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    # The alert's subscriptionId. NOTE spec 8.3.11's field table calls this
    # SubscriptionRequestId while its own example body (and ABDM's real
    # captured payload) carry subscriptionId -- the example wins, per
    # Appendix A. Nullable so a payload shaped the other way still records.
    subscription_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    patient_id: Mapped[str] = mapped_column(Text, nullable=False)
    locker_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "LINK" or "DATA".
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    hip_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The alert's own contexts[] verbatim -- careContexts + hiType per
    # entry. Stored whole rather than exploded into rows: one alert is
    # processed as one unit, and the shapes ABDM sends here are not yet
    # confirmed beyond the spec's example.
    contexts: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)

    processing_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="RECEIVED")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The consent this alert caused us to raise (or reuse, for DATA).
    consent_request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # repo/'s own health-information request id, once the fetch is fired.
    health_information_request_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    detail: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)

    __table_args__ = (
        Index("ix_locker_alert_patient_id", "patient_id"),
        Index("ix_locker_alert_processing_state", "processing_state"),
    )

    def __repr__(self) -> str:
        return (
            f"<LockerAlert id={self.id} event_id={self.event_id!r} "
            f"category={self.category!r} state={self.processing_state!r}>"
        )


class LockerPendingRequest(Base):
    """
    P20 -- correlation for an outbound HIU call whose real answer arrives
    later, on a different connection, as an ABDM callback.

    WHY THIS TABLE EXISTS AT ALL. Every section 6/7 call the locker makes
    is acknowledged 202 with an ack-only body: consent/v3/request/init
    does not return the consentRequest.id, consent/v3/fetch does not
    return the artefact, health-information/v3/request does not return the
    transactionId. All three arrive later on an inbound callback that
    identifies itself ONLY by echoing our own REQUEST-ID header. With
    nothing stored at call time there is no way to know which patient,
    which consent or which alert a given callback belongs to.

    ONE TABLE, NOT THREE, discriminated by `kind`. repo/ splits this
    across pending_consent_request_repository and
    pending_health_information_request_repository; the split buys nothing
    here -- the lookup is always "give me the row for this REQUEST-ID" and
    the columns are near-identical. `kind` keeps the three flows readable
    and lets a handler assert it got the shape it expected.

    NOT A CACHE. A row here is the only record that an outbound call was
    ever made, so it is written BEFORE the request goes out -- a callback
    that beats our own HTTP response back (seen in the sandbox) still
    finds its session. Rows are kept after resolution, deliberately: they
    are the audit trail for "we asked ABDM for X at time T".
    """

    __tablename__ = "locker_pending_request"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Our own REQUEST-ID header on the outbound call -- the only thing the
    # matching callback echoes back, hence the dedupe/lookup key.
    request_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    # "CONSENT_INIT" | "CONSENT_FETCH" | "HI_REQUEST".
    kind: Mapped[str] = mapped_column(Text, nullable=False)

    patient_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    hiu_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    hip_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Filled in on the way OUT where known (consent fetch, HI request) and
    # on the way BACK where not (a consent init learns its
    # consent_request_id only from the on-init callback).
    consent_request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # HI_REQUEST only -- ABDM's transactionId, delivered by on-request and
    # then used to match the HIP's own data push.
    transaction_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The locker alert that caused this call, when there is one. Lets a
    # callback advance locker_alert.processing_state without the caller
    # having to thread the event id through ABDM and back -- the missing
    # link that left alerts stuck at CONSENT_REQUESTED before P20.
    alert_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "PENDING" | "RESOLVED" | "FAILED".
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    detail: Mapped[Any | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_locker_pending_request_kind", "kind"),
        Index("ix_locker_pending_request_transaction_id", "transaction_id"),
        Index("ix_locker_pending_request_consent_id", "consent_id"),
        Index("ix_locker_pending_request_alert_event_id", "alert_event_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<LockerPendingRequest id={self.id} request_id={self.request_id!r} "
            f"kind={self.kind!r} state={self.state!r}>"
        )


class LockerConsentArtefact(Base):
    """
    P20 -- a GRANTED consent artefact as delivered by section 6's on-fetch
    callback, keyed by ABDM's own consentDetail.consentId.

    THIS IS THE TABLE THAT MAKES A DATA REQUEST POSSIBLE. Section 7.3.1's
    health-information request must carry a consentId the HIU actually
    holds the artefact for, and its dateRange must fall inside the
    artefact's approved permission window -- both checks need the artefact
    itself, not just the id. Before P20 the locker read these out of
    repo/'s hiu_consent_repository, which is why a locker running without
    repo/ could raise consents and then never use them.

    ONLY EVER OUR OWN. Every row here arrives via an on-fetch callback for
    a fetch WE initiated, for a consent WE raised as the locker. That is a
    deliberate security property, not an accident of implementation: the
    deleted discover_self_view_consents() workaround used to write another
    app's consents into repo/'s cache so this app could pull data under
    them. Nothing can put a foreign consent in this table.

    The whole artefact is kept verbatim in `artefact` alongside the
    extracted columns -- the extracted ones are what we query on, the
    verbatim one is what we can re-read when a shape turns out to differ
    from the spec example.
    """

    __tablename__ = "locker_consent_artefact"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    consent_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    consent_request_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    patient_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    hiu_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    hip_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "GRANTED" | "REVOKED" | "EXPIRED". Updated in place when a later
    # notify tells us the patient revoked -- the artefact row stays, its
    # status changes, so an audit of "what did we hold and when" survives.
    status: Mapped[str | None] = mapped_column(Text, nullable=True)

    # consentDetail.hiTypes verbatim (a JSON list).
    hi_types: Mapped[Any | None] = mapped_column(JSONB, nullable=True)

    # consentDetail.permission.dateRange -- the window a health-information
    # request's own dateRange must sit inside.
    permission_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    permission_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_erase_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The full consentDetail, and ABDM's detached signature over it.
    artefact: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_locker_consent_artefact_patient_id", "patient_id"),
        Index("ix_locker_consent_artefact_consent_request_id", "consent_request_id"),
        Index("ix_locker_consent_artefact_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<LockerConsentArtefact id={self.id} consent_id={self.consent_id!r} "
            f"status={self.status!r}>"
        )


class LockerHealthInformation(Base):
    """
    P20 -- decrypted record content from a section 7 transfer, one row per
    ABDM transactionId.

    OVERWRITTEN ON EVERY PAGE, BY DESIGN. A multi-care-context transfer
    arrives as several pushes (one page per care context), each carrying
    its own page_number/page_count. Each push merges its entries into
    care_contexts and rewrites this row, so the row always holds
    everything received so far. A reader must therefore check
    page_number >= page_count - 1 before treating the row as complete --
    exactly the bug fixed in data_flow.get_health_information_status() on
    2026-09-05, preserved here as the table's own contract rather than
    left as a caller-side convention.

    DECRYPTED, NOT RAW. The ECDH/AES pipeline (abdm_core/fidelius.py) runs
    in the push handler before anything is written, so nothing encrypted
    and no key material is ever persisted -- the transfer's ephemeral keys
    live only in locker_pending_request.detail for the life of the transfer.
    """

    __tablename__ = "locker_health_information"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    transaction_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    patient_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    hip_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Latest page seen. See this class's own docstring for why a reader
    # must compare these before calling a transfer complete.
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # {careContextReference: {"status": ..., "entries": [...]}} -- merged
    # across every page received so far.
    care_contexts: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)

    # "OK" | "ERRORED" | "PARTIAL" -- our own roll-up, not an ABDM field.
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_locker_health_information_patient_id", "patient_id"),
        Index("ix_locker_health_information_consent_id", "consent_id"),
        Index("ix_locker_health_information_request_id", "request_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<LockerHealthInformation id={self.id} transaction_id={self.transaction_id!r} "
            f"page={self.page_number}/{self.page_count} status={self.status!r}>"
        )
