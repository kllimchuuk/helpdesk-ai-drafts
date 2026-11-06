"""create llm calls table

Revision ID: b7d2f4a91c36
Revises: 8c4e1b7a2d90
Create Date: 2026-11-07 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d2f4a91c36"
down_revision: str | None = "8c4e1b7a2d90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "called_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.CheckConstraint("kind IN ('provider', 'keyless')", name="ck_llm_calls_kind"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_calls_called_at", "llm_calls", ["called_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_called_at", table_name="llm_calls")
    op.drop_table("llm_calls")
