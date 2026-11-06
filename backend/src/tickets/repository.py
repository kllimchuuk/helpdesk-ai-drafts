from abc import ABC, abstractmethod
from typing import Annotated

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, translate_unavailable
from tickets.models import TicketEvent


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


def get_ticket_repository(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TicketRepository:
    return TicketRepositoryImpl(session)
