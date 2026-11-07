import uuid
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, translate_unavailable
from tickets.models import TicketEvent
from tickets.schemas import ClaimedTicket
from tickets.status import TicketStatus


class TicketRepository(ABC):
    @abstractmethod
    async def insert_if_new(
        self,
        *,
        event_id: str,
        ticket_id: str,
        customer_email: str,
        message: str,
        reply_url: str,
    ) -> bool:
        raise NotImplementedError()

    @abstractmethod
    async def count_by_status(self) -> dict[str, int]:
        raise NotImplementedError()

    @abstractmethod
    async def list_recent(
        self, status: TicketStatus | None, limit: int
    ) -> list[TicketEvent]:
        raise NotImplementedError()

    @abstractmethod
    async def get(self, ticket_id: uuid.UUID) -> TicketEvent | None:
        raise NotImplementedError()

    @abstractmethod
    async def review(
        self, ticket_id: uuid.UUID, decision: TicketStatus
    ) -> TicketEvent | None:
        """Move a `draft_ready` ticket to `decision`; None if it was not ready."""
        raise NotImplementedError()

    @abstractmethod
    async def claim_for_generation(
        self, limit: int, lease_seconds: float
    ) -> list[ClaimedTicket]:
        """Lease due `received` rows and expired `generating` ones."""
        raise NotImplementedError()

    @abstractmethod
    async def extend_generation_lease(
        self, ticket: ClaimedTicket, lease_seconds: float
    ) -> bool:
        raise NotImplementedError()

    @abstractmethod
    async def save_draft(
        self,
        ticket: ClaimedTicket,
        *,
        text: str,
        sources: list[dict[str, str]],
        low_confidence: bool,
        is_static: bool,
    ) -> bool:
        raise NotImplementedError()

    @abstractmethod
    async def retry_generation(
        self, ticket: ClaimedTicket, *, delay_seconds: float, error: str
    ) -> bool:
        raise NotImplementedError()

    @abstractmethod
    async def fail_generation(self, ticket: ClaimedTicket, *, error: str) -> bool:
        raise NotImplementedError()


class TicketRepositoryImpl(TicketRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @translate_unavailable
    async def insert_if_new(
        self,
        *,
        event_id: str,
        ticket_id: str,
        customer_email: str,
        message: str,
        reply_url: str,
    ) -> bool:
        statement = (
            insert(TicketEvent)
            .values(
                event_id=event_id,
                ticket_id=ticket_id,
                customer_email=customer_email,
                message=message,
                reply_url=reply_url,
            )
            .on_conflict_do_nothing(index_elements=[TicketEvent.event_id])
            .returning(TicketEvent.id)
        )
        inserted = (await self._session.execute(statement)).first() is not None
        # The webhook acknowledgement must follow a durable write, so commit here
        # instead of relying on get_db to commit after the response is built.
        await self._session.commit()
        return inserted

    @translate_unavailable
    async def count_by_status(self) -> dict[str, int]:
        rows = await self._session.execute(
            select(TicketEvent.status, func.count()).group_by(TicketEvent.status)
        )
        return dict(rows.all())

    @translate_unavailable
    async def list_recent(
        self, status: TicketStatus | None, limit: int
    ) -> list[TicketEvent]:
        statement = (
            select(TicketEvent)
            .order_by(TicketEvent.created_at.desc(), TicketEvent.id.desc())
            .limit(limit)
        )
        if status is not None:
            statement = statement.where(TicketEvent.status == status)
        return list(await self._session.scalars(statement))

    @translate_unavailable
    async def get(self, ticket_id: uuid.UUID) -> TicketEvent | None:
        return await self._session.get(TicketEvent, ticket_id)

    @translate_unavailable
    async def review(
        self, ticket_id: uuid.UUID, decision: TicketStatus
    ) -> TicketEvent | None:
        # One conditional UPDATE: of any number of simultaneous clicks only the
        # first finds the row in `draft_ready`, so a reply is approved once (I7).
        row = await self._session.scalar(
            update(TicketEvent)
            .where(
                TicketEvent.id == ticket_id,
                TicketEvent.status == TicketStatus.DRAFT_READY,
            )
            .values(
                status=decision,
                reviewed_at=func.now(),
                next_attempt_at=func.now(),
                locked_until=None,
            )
            .returning(TicketEvent)
        )
        await self._session.commit()
        return row

    @translate_unavailable
    async def claim_for_generation(
        self, limit: int, lease_seconds: float
    ) -> list[ClaimedTicket]:
        due = (
            select(TicketEvent.id)
            .where(
                TicketEvent.status.in_(
                    [TicketStatus.RECEIVED, TicketStatus.GENERATING]
                ),
                TicketEvent.next_attempt_at <= func.now(),
                or_(
                    TicketEvent.locked_until.is_(None),
                    TicketEvent.locked_until < func.now(),
                ),
            )
            .order_by(TicketEvent.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        # A `generating` row with an expired lease belongs to a worker that died;
        # taking it again bumps the attempt, which also fences the dead worker out.
        rows = await self._session.execute(
            update(TicketEvent)
            .where(TicketEvent.id.in_(due.scalar_subquery()))
            .values(
                status=TicketStatus.GENERATING,
                gen_attempts=TicketEvent.gen_attempts + 1,
                locked_until=func.now() + timedelta(seconds=lease_seconds),
            )
            .returning(
                TicketEvent.id,
                TicketEvent.event_id,
                TicketEvent.ticket_id,
                TicketEvent.message,
                TicketEvent.gen_attempts,
            )
        )
        claimed = [
            ClaimedTicket(
                id=row.id,
                event_id=row.event_id,
                ticket_id=row.ticket_id,
                message=row.message,
                attempt=row.gen_attempts,
            )
            for row in rows
        ]
        await self._session.commit()
        return claimed

    async def extend_generation_lease(
        self, ticket: ClaimedTicket, lease_seconds: float
    ) -> bool:
        return await self._finish_generation(
            ticket, locked_until=func.now() + timedelta(seconds=lease_seconds)
        )

    async def save_draft(
        self,
        ticket: ClaimedTicket,
        *,
        text: str,
        sources: list[dict[str, str]],
        low_confidence: bool,
        is_static: bool,
    ) -> bool:
        return await self._finish_generation(
            ticket,
            status=TicketStatus.DRAFT_READY,
            draft_text=text,
            draft_sources=sources,
            low_confidence=low_confidence,
            draft_is_static=is_static,
            locked_until=None,
            last_error=None,
        )

    async def retry_generation(
        self, ticket: ClaimedTicket, *, delay_seconds: float, error: str
    ) -> bool:
        return await self._finish_generation(
            ticket,
            status=TicketStatus.RECEIVED,
            next_attempt_at=func.now() + timedelta(seconds=delay_seconds),
            locked_until=None,
            last_error=error,
        )

    async def fail_generation(self, ticket: ClaimedTicket, *, error: str) -> bool:
        return await self._finish_generation(
            ticket,
            status=TicketStatus.GENERATION_FAILED,
            locked_until=None,
            last_error=error,
        )

    @translate_unavailable
    async def _finish_generation(self, ticket: ClaimedTicket, **values: Any) -> bool:
        # Compare-and-set on the attempt: a worker whose lease expired and was
        # taken over cannot overwrite what the new owner writes.
        row = await self._session.execute(
            update(TicketEvent)
            .where(
                TicketEvent.id == ticket.id,
                TicketEvent.status == TicketStatus.GENERATING,
                TicketEvent.gen_attempts == ticket.attempt,
            )
            .values(**values)
            .returning(TicketEvent.id)
        )
        updated = row.first() is not None
        await self._session.commit()
        return updated


def get_ticket_repository(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TicketRepository:
    return TicketRepositoryImpl(session)
