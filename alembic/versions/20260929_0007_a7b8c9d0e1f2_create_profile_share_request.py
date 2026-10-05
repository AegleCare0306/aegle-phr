"""create profile_share_request

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-29

P22 -- local tracking table for spec section 5's Scan & Share, patient
side -- see aegle_phr/models.py:ProfileShareRequest for why `source` and a
Text `token_expiry` are the shapes they are. Written by hand, same style
as the six migrations before it.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profile_share_request",
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
        sa.Column("hip_id", sa.Text(), nullable=False),
        sa.Column("counter_id", sa.Text(), nullable=False),
        sa.Column("abha_address", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("token_number", sa.Text(), nullable=True),
        sa.Column("token_expiry", sa.Text(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_profile_share_request"),
        sa.UniqueConstraint("request_id", name="uq_profile_share_request_request_id"),
    )

    # Candidate A's fallback correlation (abhaAddress + counter, newest
    # PENDING first) reads on exactly this pair -- see
    # aegle_phr/callbacks/profile_share_services.py.
    op.create_index(
        "ix_profile_share_request_abha_counter",
        "profile_share_request",
        ["abha_address", "counter_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_profile_share_request_abha_counter", table_name="profile_share_request")
    op.drop_table("profile_share_request")
