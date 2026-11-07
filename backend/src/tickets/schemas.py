import uuid
from dataclasses import dataclass

from pydantic import BaseModel


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
