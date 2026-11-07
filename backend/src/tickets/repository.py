import uuid
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import ColumnElement, Select, func, or_, select, true, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, translate_unavailable
from tickets.models import TicketEvent
from tickets.schemas import ClaimedSend, ClaimedTicket
from tickets.status import TicketStatus


class TicketRepository(ABC):
    @abstractmethod
    async def insert_if_new(
        self,
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
    async def list_recent(self, limit: int) -> list[TicketEvent]:
        raise NotImplementedError()

    @abstractmethod
    async def list_by_status(
        self, status: TicketStatus, limit: int
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
    async def mark_unknown_delivered(self, ticket_id: uuid.UUID) -> TicketEvent | None:
        """Move a `send_unknown` ticket to `sent`; None if it was not unknown."""
        raise NotImplementedError()

    @abstractmethod
    async def requeue_unknown(self, ticket_id: uuid.UUID) -> TicketEvent | None:
        """Move a `send_unknown` ticket back to `approved`; None if it was not."""
        raise NotImplementedError()

    @abstractmethod
    async def claim_for_sending(
        self, limit: int, lease_seconds: float
    ) -> list[TicketEvent]:
        raise NotImplementedError()

    @abstractmethod
    async def requeue_stale_sends(self, max_attempts: int, error: str) -> int:
        """Put expired `sending` rows below `max_attempts` back to `approved`."""
        raise NotImplementedError()

    @abstractmethod
    async def park_stale_sends(self, error: str) -> int:
        """Move expired `sending` rows to `send_unknown`; returns how many."""
        raise NotImplementedError()

    @abstractmethod
    async def mark_sent(self, ticket: ClaimedSend) -> bool:
        raise NotImplementedError()

    @abstractmethod
    async def retry_send(
        self, ticket: ClaimedSend, delay_seconds: float, error: str
    ) -> bool:
        raise NotImplementedError()

    @abstractmethod
    async def fail_send(self, ticket: ClaimedSend, error: str) -> bool:
        raise NotImplementedError()

    @abstractmethod
    async def park_unknown(self, ticket: ClaimedSend, error: str) -> bool:
        raise NotImplementedError()

    @abstractmethod
    async def claim_for_generation(
        self, limit: int, lease_seconds: float
    ) -> list[TicketEvent]:
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
        text: str,
        sources: list[dict[str, str]],
        low_confidence: bool,
        is_static: bool,
    ) -> bool:
        raise NotImplementedError()

    @abstractmethod
    async def retry_generation(
        self, ticket: ClaimedTicket, delay_seconds: float, error: str
    ) -> bool:
        raise NotImplementedError()

    @abstractmethod
    async def fail_generation(self, ticket: ClaimedTicket, error: str) -> bool:
        raise NotImplementedError()


class TicketRepositoryImpl(TicketRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @translate_unavailable
    async def insert_if_new(
        self,
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
    async def list_recent(self, limit: int) -> list[TicketEvent]:
        return list(await self._session.scalars(self._newest_first(limit)))

    @translate_unavailable
    async def list_by_status(
        self, status: TicketStatus, limit: int
    ) -> list[TicketEvent]:
        statement = self._newest_first(limit).where(TicketEvent.status == status)
        return list(await self._session.scalars(statement))

    @staticmethod
    def _newest_first(limit: int) -> Select[tuple[TicketEvent]]:
        return (
            select(TicketEvent)
            .order_by(TicketEvent.created_at.desc(), TicketEvent.id.desc())
            .limit(limit)
        )

    @translate_unavailable
    async def get(self, ticket_id: uuid.UUID) -> TicketEvent | None:
        return await self._session.get(TicketEvent, ticket_id)

    async def review(
        self, ticket_id: uuid.UUID, decision: TicketStatus
    ) -> TicketEvent | None:
        return await self._operator_transition(
            ticket_id,
            TicketStatus.DRAFT_READY,
            {
                "status": decision,
                "reviewed_at": func.now(),
                "next_attempt_at": func.now(),
                "locked_until": None,
            },
        )

    async def mark_unknown_delivered(self, ticket_id: uuid.UUID) -> TicketEvent | None:
        return await self._operator_transition(
            ticket_id,
            TicketStatus.SEND_UNKNOWN,
            {"status": TicketStatus.SENT, "sent_at": func.now(), "last_error": None},
        )

    async def requeue_unknown(self, ticket_id: uuid.UUID) -> TicketEvent | None:
        return await self._operator_transition(
            ticket_id,
            TicketStatus.SEND_UNKNOWN,
            {
                "status": TicketStatus.APPROVED,
                "next_attempt_at": func.now(),
                "locked_until": None,
            },
        )

    @translate_unavailable
    async def _operator_transition(
        self, ticket_id: uuid.UUID, expected: TicketStatus, values: dict[str, Any]
    ) -> TicketEvent | None:
        # One conditional UPDATE: of any number of simultaneous clicks only the
        # first finds the row in the expected status, so it changes once (I7).
        row = await self._session.scalar(
            update(TicketEvent)
            .where(TicketEvent.id == ticket_id, TicketEvent.status == expected)
            .values(values)
            .returning(TicketEvent)
        )
        await self._session.commit()
        return row

    @translate_unavailable
    async def claim_for_generation(
        self, limit: int, lease_seconds: float
    ) -> list[TicketEvent]:
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
        rows = await self._session.scalars(
            update(TicketEvent)
            .where(TicketEvent.id.in_(due.scalar_subquery()))
            .values(
                status=TicketStatus.GENERATING,
                gen_attempts=TicketEvent.gen_attempts + 1,
                locked_until=func.now() + timedelta(seconds=lease_seconds),
            )
            .returning(TicketEvent)
        )
        claimed = list(rows)
        await self._session.commit()
        return claimed

    async def extend_generation_lease(
        self, ticket: ClaimedTicket, lease_seconds: float
    ) -> bool:
        return await self._finish_generation(
            ticket, {"locked_until": func.now() + timedelta(seconds=lease_seconds)}
        )

    async def save_draft(
        self,
        ticket: ClaimedTicket,
        text: str,
        sources: list[dict[str, str]],
        low_confidence: bool,
        is_static: bool,
    ) -> bool:
        return await self._finish_generation(
            ticket,
            {
                "status": TicketStatus.DRAFT_READY,
                "draft_text": text,
                "draft_sources": sources,
                "low_confidence": low_confidence,
                "draft_is_static": is_static,
                "locked_until": None,
                "last_error": None,
            },
        )

    async def retry_generation(
        self, ticket: ClaimedTicket, delay_seconds: float, error: str
    ) -> bool:
        return await self._finish_generation(
            ticket,
            {
                "status": TicketStatus.RECEIVED,
                "next_attempt_at": func.now() + timedelta(seconds=delay_seconds),
                "locked_until": None,
                "last_error": error,
            },
        )

    async def fail_generation(self, ticket: ClaimedTicket, error: str) -> bool:
        return await self._finish_generation(
            ticket,
            {
                "status": TicketStatus.GENERATION_FAILED,
                "locked_until": None,
                "last_error": error,
            },
        )

    async def _finish_generation(
        self, ticket: ClaimedTicket, values: dict[str, Any]
    ) -> bool:
        return await self._finish(
            ticket.id,
            TicketStatus.GENERATING,
            TicketEvent.gen_attempts == ticket.attempt,
            values,
        )

    @translate_unavailable
    async def claim_for_sending(
        self, limit: int, lease_seconds: float
    ) -> list[TicketEvent]:
        due = (
            select(TicketEvent.id)
            .where(
                TicketEvent.status == TicketStatus.APPROVED,
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
        rows = await self._session.scalars(
            update(TicketEvent)
            .where(TicketEvent.id.in_(due.scalar_subquery()))
            .values(
                status=TicketStatus.SENDING,
                send_attempts=TicketEvent.send_attempts + 1,
                locked_until=func.now() + timedelta(seconds=lease_seconds),
            )
            .returning(TicketEvent)
        )
        claimed = list(rows)
        await self._session.commit()
        return claimed

    async def requeue_stale_sends(self, max_attempts: int, error: str) -> int:
        return await self._settle_stale_sends(
            TicketStatus.APPROVED,
            error,
            TicketEvent.send_attempts < max_attempts,
        )

    async def park_stale_sends(self, error: str) -> int:
        return await self._settle_stale_sends(TicketStatus.SEND_UNKNOWN, error, true())

    @translate_unavailable
    async def _settle_stale_sends(
        self, status: TicketStatus, error: str, condition: ColumnElement[bool]
    ) -> int:
        # A `sending` row whose lease expired belongs to a worker that died during
        # the request; one conditional UPDATE moves each such row exactly once.
        rows = await self._session.execute(
            update(TicketEvent)
            .where(
                TicketEvent.status == TicketStatus.SENDING,
                TicketEvent.locked_until < func.now(),
                condition,
            )
            .values(
                status=status,
                next_attempt_at=func.now(),
                locked_until=None,
                last_error=error,
            )
            .returning(TicketEvent.id)
        )
        settled = len(rows.all())
        await self._session.commit()
        return settled

    async def mark_sent(self, ticket: ClaimedSend) -> bool:
        return await self._finish_send(
            ticket,
            {
                "status": TicketStatus.SENT,
                "sent_at": func.now(),
                "locked_until": None,
                "last_error": None,
            },
        )

    async def retry_send(
        self, ticket: ClaimedSend, delay_seconds: float, error: str
    ) -> bool:
        return await self._finish_send(
            ticket,
            {
                "status": TicketStatus.APPROVED,
                "next_attempt_at": func.now() + timedelta(seconds=delay_seconds),
                "locked_until": None,
                "last_error": error,
            },
        )

    async def fail_send(self, ticket: ClaimedSend, error: str) -> bool:
        return await self._finish_send(
            ticket,
            {
                "status": TicketStatus.SEND_FAILED,
                "locked_until": None,
                "last_error": error,
            },
        )

    async def park_unknown(self, ticket: ClaimedSend, error: str) -> bool:
        return await self._finish_send(
            ticket,
            {
                "status": TicketStatus.SEND_UNKNOWN,
                "locked_until": None,
                "last_error": error,
            },
        )

    async def _finish_send(self, ticket: ClaimedSend, values: dict[str, Any]) -> bool:
        return await self._finish(
            ticket.id,
            TicketStatus.SENDING,
            TicketEvent.send_attempts == ticket.attempt,
            values,
        )

    @translate_unavailable
    async def _finish(
        self,
        ticket_id: uuid.UUID,
        stage: TicketStatus,
        same_attempt: ColumnElement[bool],
        values: dict[str, Any],
    ) -> bool:
        # Compare-and-set on the attempt: a worker whose lease expired and was
        # taken over cannot overwrite what the new owner writes.
        row = await self._session.execute(
            update(TicketEvent)
            .where(
                TicketEvent.id == ticket_id, TicketEvent.status == stage, same_attempt
            )
            .values(values)
            .returning(TicketEvent.id)
        )
        updated = row.first() is not None
        await self._session.commit()
        return updated


def get_ticket_repository(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TicketRepository:
    return TicketRepositoryImpl(session)
