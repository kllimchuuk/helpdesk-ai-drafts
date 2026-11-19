import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from llm.repository import LlmCallRepositoryImpl
from tickets.repository import TicketRepositoryImpl
from tickets.status import TicketStatus

logger = logging.getLogger(__name__)

FINISHED_STATUSES = (
    TicketStatus.SENT,
    TicketStatus.REJECTED,
    TicketStatus.GENERATION_FAILED,
    TicketStatus.SEND_FAILED,
)
DAY_SECONDS = 86_400.0
LLM_CALL_RETENTION_SECONDS = 2 * DAY_SECONDS


@dataclass(frozen=True)
class PrunePolicy:
    ticket_retention_seconds: float = 30 * DAY_SECONDS
    llm_call_retention_seconds: float = LLM_CALL_RETENTION_SECONDS
    interval_seconds: float = 3600.0


class PruneLoop:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        policy: PrunePolicy,
    ) -> None:
        self._session_factory = session_factory
        self._policy = policy

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.prune_once()
            except Exception:
                logger.exception("Prune failed")
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    stop.wait(), timeout=self._policy.interval_seconds
                )

    async def prune_once(self) -> None:
        async with self._session_factory() as session:
            tickets = await TicketRepositoryImpl(session).delete_finished_older_than(
                list(FINISHED_STATUSES), self._policy.ticket_retention_seconds
            )
            await session.commit()
        async with self._session_factory() as session:
            calls = await LlmCallRepositoryImpl(session).delete_older_than(
                self._policy.llm_call_retention_seconds
            )
            await session.commit()
        if tickets or calls:
            logger.info("Pruned %d tickets and %d llm calls", tickets, calls)
