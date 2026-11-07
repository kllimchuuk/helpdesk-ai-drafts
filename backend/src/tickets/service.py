import uuid
from typing import Annotated

from fastapi import Depends

from tickets.exceptions import TicketNotFoundError, TicketStatusConflictError
from tickets.models import TicketEvent
from tickets.repository import TicketRepository, get_ticket_repository
from tickets.schemas import (
    StatsResponse,
    TicketDetail,
    TicketListResponse,
    TicketSummary,
)
from tickets.status import TicketStatus

PREVIEW_LENGTH = 160
REVIEW_ATTEMPTS = 2


class TicketService:
    def __init__(self, repository: TicketRepository) -> None:
        self._repository = repository

    async def stats(self) -> StatsResponse:
        found = await self._repository.count_by_status()
        counts = {status.value: found.get(status.value, 0) for status in TicketStatus}
        return StatsResponse(counts=counts, total=sum(counts.values()))

    async def list_tickets(
        self, status: TicketStatus | None, limit: int
    ) -> TicketListResponse:
        rows = await self._repository.list_recent(status, limit)
        return TicketListResponse(items=[summarize(row) for row in rows])

    async def get_ticket(self, ticket_id: str) -> TicketDetail:
        return TicketDetail.model_validate(await self._load(ticket_id))

    async def approve(self, ticket_id: str) -> TicketDetail:
        return await self._review(ticket_id, TicketStatus.APPROVED)

    async def reject(self, ticket_id: str) -> TicketDetail:
        return await self._review(ticket_id, TicketStatus.REJECTED)

    async def _review(self, ticket_id: str, decision: TicketStatus) -> TicketDetail:
        # A miss followed by a `draft_ready` read means the worker saved the draft
        # in between; one more attempt reviews it instead of a confusing 409.
        for _ in range(REVIEW_ATTEMPTS):
            row = await self._repository.review(parse_id(ticket_id), decision)
            if row is not None:
                return TicketDetail.model_validate(row)
            current = await self._load(ticket_id)
            if current.status != TicketStatus.DRAFT_READY:
                break
        raise TicketStatusConflictError(current.status)

    async def _load(self, ticket_id: str) -> TicketEvent:
        row = await self._repository.get(parse_id(ticket_id))
        if row is None:
            raise TicketNotFoundError()
        return row


def parse_id(ticket_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(ticket_id)
    except ValueError:
        raise TicketNotFoundError() from None


def summarize(row: TicketEvent) -> TicketSummary:
    preview = row.message
    if len(preview) > PREVIEW_LENGTH:
        preview = preview[:PREVIEW_LENGTH] + "…"
    return TicketSummary(
        id=row.id,
        event_id=row.event_id,
        ticket_id=row.ticket_id,
        status=row.status,
        message_preview=preview,
        low_confidence=row.low_confidence,
        draft_is_static=row.draft_is_static,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def get_ticket_service(
    repository: Annotated[TicketRepository, Depends(get_ticket_repository)],
) -> TicketService:
    return TicketService(repository)
