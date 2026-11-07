"""add draft_is_static to ticket events

Revision ID: e3a9c51d7f20
Revises: b7d2f4a91c36
Create Date: 2026-11-07 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3a9c51d7f20"
down_revision: str | None = "b7d2f4a91c36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ticket_events",
        sa.Column(
            "draft_is_static",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("ticket_events", "draft_is_static")
