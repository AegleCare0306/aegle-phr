"""create abdm_call_log

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-27

Archive of outbound ABDM calls -- see aegle_phr/models.py:AbdmCallLog.
Written by hand, same style as the callback_log migration, so the JSONB and
timestamptz choices stay explicit.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "abdm_call_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "called_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("abdm_url", sa.Text(), nullable=False),
        # JSONB so these can be queried into when recovering the
        # undocumented response shapes after a live run.
        sa.Column("request_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_abdm_call_log"),
    )

    op.create_index("ix_abdm_call_log_called_at", "abdm_call_log", ["called_at"])
    op.create_index("ix_abdm_call_log_route", "abdm_call_log", ["route"])


def downgrade() -> None:
    op.drop_index("ix_abdm_call_log_route", table_name="abdm_call_log")
    op.drop_index("ix_abdm_call_log_called_at", table_name="abdm_call_log")
    op.drop_table("abdm_call_log")
