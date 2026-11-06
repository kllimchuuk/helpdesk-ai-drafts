from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.base_model import Base
from core.sql import enum_check
from llm.route import LlmRoute


class LlmCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        enum_check("kind", "ck_llm_calls_kind", LlmRoute),
        Index("ix_llm_calls_called_at", "called_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    kind: Mapped[str] = mapped_column(String(16))
