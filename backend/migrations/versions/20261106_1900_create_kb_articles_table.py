"""create kb articles table

Revision ID: 8c4e1b7a2d90
Revises: 3f1c2a9d7b44
Create Date: 2026-11-06 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8c4e1b7a2d90"
down_revision: str | None = "3f1c2a9d7b44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "kb_articles",
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', title || ' ' || body)", persisted=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("slug"),
    )
    op.create_index(
        "ix_kb_articles_tsv", "kb_articles", ["tsv"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_kb_articles_tsv", table_name="kb_articles", postgresql_using="gin"
    )
    op.drop_table("kb_articles")
