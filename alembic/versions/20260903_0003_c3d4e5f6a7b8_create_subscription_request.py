"""create subscription_request

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-03

P13 -- local tracking table for spec §8's Subscription Flow -- see
aegle_phr/models.py:SubscriptionRequest. Written by hand, same style as
the callback_log/abdm_call_log migrations.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_request",
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
        sa.Column("subscription_request_id", sa.Text(), nullable=True),
        sa.Column("subscription_id", sa.Text(), nullable=True),
        sa.Column("patient_id", sa.Text(), nullable=False),
        sa.Column("hiu_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="REQUESTED", nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_subscription_request"),
        sa.UniqueConstraint("request_id", name="uq_subscription_request_request_id"),
    )

    op.create_index(
        "ix_subscription_request_subscription_request_id",
        "subscription_request",
        ["subscription_request_id"],
    )
    op.create_index("ix_subscription_request_patient_id", "subscription_request", ["patient_id"])


def downgrade() -> None:
    op.drop_index("ix_subscription_request_patient_id", table_name="subscription_request")
    op.drop_index("ix_subscription_request_subscription_request_id", table_name="subscription_request")
    op.drop_table("subscription_request")
