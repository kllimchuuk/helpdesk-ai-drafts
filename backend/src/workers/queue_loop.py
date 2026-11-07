import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions import DatabaseUnavailableError
from tickets.repository import TicketRepository, TicketRepositoryImpl

logger = logging.getLogger(__name__)


class Job(Protocol):
    event_id: str
    ticket_id: str
    attempt: int


class QueueLoop[J: Job](ABC):
    """Claims jobs from one stage of `ticket_events` and works on them in tasks."""

    name: str

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        concurrency: int,
        poll_seconds: float,
    ) -> None:
        self._session_factory = session_factory
        self._concurrency = concurrency
        self._poll_seconds = poll_seconds
        self._in_flight: set[asyncio.Task[None]] = set()

    async def run(self, stop: asyncio.Event) -> None:
        stopping = asyncio.create_task(stop.wait())
        try:
            while not stop.is_set():
                free = self._concurrency - len(self._in_flight)
                claimed = await self._claim(free) if free else []
                for job in claimed:
                    task = asyncio.create_task(self._process(job))
                    self._in_flight.add(task)
                    task.add_done_callback(self._forget)
                if claimed and len(claimed) == free:
                    continue
                await asyncio.wait(
                    [stopping, *self._in_flight],
                    timeout=self._poll_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
        finally:
            stopping.cancel()
            # Leases of cancelled jobs expire and the stage's recovery takes over.
            for task in self._in_flight:
                task.cancel()
            await asyncio.gather(*self._in_flight, return_exceptions=True)

    @abstractmethod
    async def _claim_batch(self, tickets: TicketRepository, limit: int) -> list[J]:
        raise NotImplementedError()

    @abstractmethod
    async def _process(self, job: J) -> None:
        raise NotImplementedError()

    def _forget(self, task: asyncio.Task[None]) -> None:
        self._in_flight.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error(f"{self.name} task crashed", exc_info=task.exception())

    async def _claim(self, limit: int) -> list[J]:
        try:
            async with self._tickets() as tickets:
                return await self._claim_batch(tickets, limit)
        except DatabaseUnavailableError:
            logger.warning(f"Database unavailable, {self.name} claim skipped")
        except Exception:
            logger.exception(f"{self.name} claim failed")
        return []

    async def _write(
        self,
        job: J,
        outcome: str,
        action: Callable[[TicketRepository], Awaitable[bool]],
    ) -> None:
        try:
            async with self._tickets() as tickets:
                written = await action(tickets)
        except DatabaseUnavailableError:
            log(logging.WARNING, "Database unavailable, result dropped", job)
            return
        except Exception:
            log(logging.ERROR, "Result write failed", job, exc_info=True)
            return
        if written:
            log(logging.INFO, f"{self.name} outcome: {outcome}", job)
        else:
            log(logging.WARNING, "Lease lost, result dropped", job)

    @asynccontextmanager
    async def _tickets(self) -> AsyncIterator[TicketRepository]:
        async with self._session_factory() as session:
            yield TicketRepositoryImpl(session)


def log(level: int, message: str, job: Job, *, exc_info: bool = False) -> None:
    logger.log(
        level,
        message,
        exc_info=exc_info,
        extra={
            "event_id": job.event_id,
            "ticket_id": job.ticket_id,
            "attempt": job.attempt,
        },
    )
