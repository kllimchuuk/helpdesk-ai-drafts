"""create ticket events table

Revision ID: 3f1c2a9d7b44
Revises:
Create Date: 2026-11-06 17:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3f1c2a9d7b44"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = (
    "received",
    "generating",
    "draft_ready",
    "approved",
    "sending",
    "sent",
    "rejected",
    "generation_failed",
    "send_failed",
    "send_unknown",
)


def upgrade() -> None:
    allowed = ", ".join(f"'{status}'" for status in STATUSES)
    op.create_table(
        "ticket_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("ticket_id", sa.String(length=255), nullable=False),
        sa.Column("customer_email", sa.String(length=320), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("reply_url", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="received",
            nullable=False,
        ),
        sa.Column("draft_text", sa.Text(), nullable=True),
        sa.Column("draft_sources", postgresql.JSONB(), nullable=True),
        sa.Column(
            "low_confidence",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "gen_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "send_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"status IN ({allowed})", name="ck_ticket_events_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_ticket_events_event_id"),
    )
    op.create_index(
        "ix_ticket_events_status_next_attempt_at",
        "ticket_events",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ticket_events_status_next_attempt_at", table_name="ticket_events")
    op.drop_table("ticket_events")
