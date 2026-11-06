from sqlalchemy import Computed, Index, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from core.base_model import Base


class KbArticle(Base):
    __tablename__ = "kb_articles"
    __table_args__ = (Index("ix_kb_articles_tsv", "tsv", postgresql_using="gin"),)

    slug: Mapped[str] = mapped_column(String(100), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', title || ' ' || body)", persisted=True),
    )
