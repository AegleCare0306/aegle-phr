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
