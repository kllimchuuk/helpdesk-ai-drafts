import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base_model import Base
from core.sql import enum_check
from tickets.status import TicketStatus


class TicketEvent(Base):
    __tablename__ = "ticket_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_ticket_events_event_id"),
        enum_check("status", "ck_ticket_events_status", TicketStatus),
        Index("ix_ticket_events_status_next_attempt_at", "status", "next_attempt_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[str] = mapped_column(String(255))
    ticket_id: Mapped[str] = mapped_column(String(255))
    customer_email: Mapped[str] = mapped_column(String(320))
    message: Mapped[str] = mapped_column(Text)
    reply_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32),
        default=TicketStatus.RECEIVED,
        server_default=TicketStatus.RECEIVED.value,
    )
    draft_text: Mapped[str | None] = mapped_column(Text)
    draft_sources: Mapped[list | None] = mapped_column(JSONB)
    low_confidence: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    gen_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    send_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
