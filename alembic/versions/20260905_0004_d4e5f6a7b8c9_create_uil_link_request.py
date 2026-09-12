"""create uil_link_request

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-05

P15 -- local tracking table for spec §10's User-Initiated Linking -- see
aegle_phr/models.py:UilLinkRequest. Written by hand, same style as the
callback_log/abdm_call_log/subscription_request migrations.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "uil_link_request",
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
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("hip_id", sa.Text(), nullable=False),
        sa.Column("abha_address", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("link_ref_number", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_uil_link_request"),
        sa.UniqueConstraint("request_id", name="uq_uil_link_request_request_id"),
    )

    op.create_index(
        "ix_uil_link_request_hip_abha",
        "uil_link_request",
        ["hip_id", "abha_address"],
    )


def downgrade() -> None:
    op.drop_index("ix_uil_link_request_hip_abha", table_name="uil_link_request")
    op.drop_table("uil_link_request")
