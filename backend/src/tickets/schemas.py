import uuid
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StatsResponse(BaseModel):
    counts: dict[str, int]
    total: int


@dataclass(frozen=True)
class ClaimedTicket:
    id: uuid.UUID
    event_id: str
    ticket_id: str
    message: str
    attempt: int


class DraftSourceResponse(BaseModel):
    slug: str
    title: str
    url: str


class TicketSummary(BaseModel):
    id: uuid.UUID
    event_id: str
    ticket_id: str
    status: str
    message_preview: str
    low_confidence: bool
    draft_is_static: bool
    created_at: datetime
    updated_at: datetime


class TicketListResponse(BaseModel):
    items: list[TicketSummary]


class TicketDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: str
    ticket_id: str
    customer_email: str
    message: str
    status: str
    draft_text: str | None
    draft_sources: list[DraftSourceResponse] | None
    low_confidence: bool
    draft_is_static: bool
    gen_attempts: int
    send_attempts: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None
    sent_at: datetime | None
