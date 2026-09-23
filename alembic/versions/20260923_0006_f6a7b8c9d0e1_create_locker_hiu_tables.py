"""create locker_pending_request, locker_consent_artefact and locker_health_information

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-23

P20 -- the PHR app's OWN HIU state, so the Health Locker no longer reads
consent artefacts, pending sessions and fetched record content out of
repo/'s tables. See aegle_phr/models.py's LockerPendingRequest,
LockerConsentArtefact and LockerHealthInformation for what each column is for.

PURELY ADDITIVE: three new tables, nothing existing touched. repo/'s own
hiu_consents / locker_health_information / pending_* tables are left exactly
as they are and keep serving repo/'s own HIU role -- this is a second,
independent HIU (the locker, under its own client id), not a replacement
for the first one.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "locker_pending_request",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("patient_id", sa.Text(), nullable=True),
        sa.Column("hiu_id", sa.Text(), nullable=True),
        sa.Column("hip_id", sa.Text(), nullable=True),
        sa.Column("consent_request_id", sa.Text(), nullable=True),
        sa.Column("consent_id", sa.Text(), nullable=True),
        sa.Column("transaction_id", sa.Text(), nullable=True),
        sa.Column("alert_event_id", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_locker_pending_request"),
    )
    # UNIQUE, not just indexed: request_id is the correlation key an
    # inbound callback arrives with, and two rows for one REQUEST-ID
    # would make "which call was this" unanswerable.
    op.create_unique_constraint(
        "uq_locker_pending_request_request_id", "locker_pending_request", ["request_id"]
    )
    op.create_index("ix_locker_pending_request_kind", "locker_pending_request", ["kind"])
    op.create_index(
        "ix_locker_pending_request_transaction_id", "locker_pending_request", ["transaction_id"]
    )
    op.create_index(
        "ix_locker_pending_request_consent_id", "locker_pending_request", ["consent_id"]
    )
    op.create_index(
        "ix_locker_pending_request_alert_event_id", "locker_pending_request", ["alert_event_id"]
    )

    op.create_table(
        "locker_consent_artefact",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("consent_id", sa.Text(), nullable=False),
        sa.Column("consent_request_id", sa.Text(), nullable=True),
        sa.Column("patient_id", sa.Text(), nullable=True),
        sa.Column("hiu_id", sa.Text(), nullable=True),
        sa.Column("hip_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("hi_types", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("permission_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("permission_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_erase_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("artefact", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_locker_consent_artefact"),
    )
    # UNIQUE so a redelivered on-fetch callback updates the artefact we
    # already hold instead of adding a second copy of it.
    op.create_unique_constraint(
        "uq_locker_consent_artefact_consent_id", "locker_consent_artefact", ["consent_id"]
    )
    op.create_index(
        "ix_locker_consent_artefact_patient_id", "locker_consent_artefact", ["patient_id"]
    )
    op.create_index(
        "ix_locker_consent_artefact_consent_request_id",
        "locker_consent_artefact",
        ["consent_request_id"],
    )
    op.create_index("ix_locker_consent_artefact_status", "locker_consent_artefact", ["status"])

    op.create_table(
        "locker_health_information",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("transaction_id", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("consent_id", sa.Text(), nullable=True),
        sa.Column("patient_id", sa.Text(), nullable=True),
        sa.Column("hip_id", sa.Text(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("care_contexts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_locker_health_information"),
    )
    # UNIQUE: every page of one transfer merges into the SAME row (see
    # LockerHealthInformation's own docstring), so the transaction id has to
    # be the thing a page is matched on.
    op.create_unique_constraint(
        "uq_locker_health_information_transaction_id",
        "locker_health_information",
        ["transaction_id"],
    )
    op.create_index(
        "ix_locker_health_information_patient_id", "locker_health_information", ["patient_id"]
    )
    op.create_index(
        "ix_locker_health_information_consent_id", "locker_health_information", ["consent_id"]
    )
    op.create_index(
        "ix_locker_health_information_request_id", "locker_health_information", ["request_id"]
    )


def downgrade() -> None:
    op.drop_table("locker_health_information")
    op.drop_table("locker_consent_artefact")
    op.drop_table("locker_pending_request")
