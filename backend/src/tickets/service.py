import uuid
from typing import Annotated

from fastapi import Depends

from tickets.exceptions import TicketNotFoundError, TicketStatusConflictError
from tickets.models import TicketEvent
from tickets.repository import TicketRepository, get_ticket_repository
from tickets.schemas import (
    ClaimedSend,
    ClaimedTicket,
    StatsResponse,
    TicketDetail,
    TicketListResponse,
    TicketSummary,
)
from tickets.status import TicketStatus

PREVIEW_LENGTH = 160


class TicketService:
    def __init__(self, repository: TicketRepository) -> None:
        self._repository = repository

    async def stats(self) -> StatsResponse:
        found = await self._repository.count_by_status()
        counts = {status: found.get(status.value, 0) for status in TicketStatus}
        return StatsResponse(counts=counts, total=sum(counts.values()))

    async def list_tickets(
        self, status: TicketStatus | None, limit: int
    ) -> TicketListResponse:
        if status is None:
            rows = await self._repository.list_recent(limit)
        else:
            rows = await self._repository.list_by_status(status, limit)
        return TicketListResponse(items=[summarize(row) for row in rows])

    async def get_ticket(self, ticket_id: str) -> TicketDetail:
        return TicketDetail.model_validate(await self._load(ticket_id))

    async def approve(self, ticket_id: str) -> TicketDetail:
        return await self._review(ticket_id, TicketStatus.APPROVED)

    async def reject(self, ticket_id: str) -> TicketDetail:
        return await self._review(ticket_id, TicketStatus.REJECTED)

    async def mark_delivered(self, ticket_id: str) -> TicketDetail:
        row = await self._repository.mark_unknown_delivered(parse_id(ticket_id))
        return await self._result(ticket_id, row)

    async def resend(self, ticket_id: str) -> TicketDetail:
        row = await self._repository.requeue_unknown(parse_id(ticket_id))
        return await self._result(ticket_id, row)

    async def _review(self, ticket_id: str, decision: TicketStatus) -> TicketDetail:
        row = await self._repository.review(parse_id(ticket_id), decision)
        return await self._result(ticket_id, row)

    async def _result(self, ticket_id: str, row: TicketEvent | None) -> TicketDetail:
        if row is None:
            current = await self._load(ticket_id)
            raise TicketStatusConflictError(current.status)
        return TicketDetail.model_validate(row)

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


def claimed_ticket(row: TicketEvent) -> ClaimedTicket:
    return ClaimedTicket(
        id=row.id,
        event_id=row.event_id,
        ticket_id=row.ticket_id,
        message=row.message,
        attempt=row.gen_attempts,
    )


def claimed_send(row: TicketEvent) -> ClaimedSend:
    return ClaimedSend(
        id=row.id,
        event_id=row.event_id,
        ticket_id=row.ticket_id,
        reply_url=row.reply_url,
        reply=row.draft_text,
        attempt=row.send_attempts,
    )


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
