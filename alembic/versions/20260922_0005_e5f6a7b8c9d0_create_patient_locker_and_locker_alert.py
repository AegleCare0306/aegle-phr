"""create patient_locker and locker_alert

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-22

P19 -- Health Locker state. Two new tables, see aegle_phr/models.py's own
PatientLocker and LockerAlert for what each column is for.

PURELY ADDITIVE: creates two new tables and touches nothing that already
holds rows. subscription_request (36 rows at the time of writing) is left
exactly as it is -- the HIU-initiated subscription route still uses it, and
P19 explicitly forbids dropping a table or column that holds data.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patient_locker",
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
        sa.Column("patient_id", sa.Text(), nullable=False),
        sa.Column("locker_id", sa.Text(), nullable=False),
        sa.Column("subscription_id", sa.Text(), nullable=True),
        sa.Column("consent_auto_approval_id", sa.Text(), nullable=True),
        sa.Column("subscription_request_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("categories", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("period_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opt_in_state", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("opt_in_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("initial_sync_state", sa.Text(), server_default="NOT_STARTED", nullable=False),
        sa.Column("initial_sync_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_patient_locker"),
    )
    # One row per (patient, locker) -- the idempotency guarantee behind
    # "ensure on login must never create duplicates".
    op.create_index(
        "uq_patient_locker_patient_locker",
        "patient_locker",
        ["patient_id", "locker_id"],
        unique=True,
    )

    op.create_table(
        "locker_alert",
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
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("subscription_id", sa.Text(), nullable=True),
        sa.Column("patient_id", sa.Text(), nullable=False),
        sa.Column("locker_id", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("hip_id", sa.Text(), nullable=True),
        sa.Column("contexts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("processing_state", sa.Text(), server_default="RECEIVED", nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("consent_request_id", sa.Text(), nullable=True),
        sa.Column("consent_id", sa.Text(), nullable=True),
        sa.Column("health_information_request_id", sa.Text(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_locker_alert"),
        # ABDM redelivers an unacknowledged alert -- this is what stops a
        # redelivery becoming a second consent request.
        sa.UniqueConstraint("event_id", name="uq_locker_alert_event_id"),
    )
    op.create_index("ix_locker_alert_patient_id", "locker_alert", ["patient_id"])
    op.create_index("ix_locker_alert_processing_state", "locker_alert", ["processing_state"])


def downgrade() -> None:
    op.drop_index("ix_locker_alert_processing_state", table_name="locker_alert")
    op.drop_index("ix_locker_alert_patient_id", table_name="locker_alert")
    op.drop_table("locker_alert")
    op.drop_index("uq_patient_locker_patient_locker", table_name="patient_locker")
    op.drop_table("patient_locker")
