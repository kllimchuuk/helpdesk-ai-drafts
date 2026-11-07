import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions import AppException, DatabaseUnavailableError
from drafting.schemas import Draft
from drafting.service import DraftingService
from llm.exceptions import LLMRateLimitedError, LLMRefusalError, LLMRejectedError
from tickets.repository import TicketRepository, TicketRepositoryImpl
from tickets.schemas import ClaimedTicket
from workers.backoff import backoff_seconds

logger = logging.getLogger(__name__)

TERMINAL_ERRORS = (LLMRejectedError, LLMRefusalError)
LEASE_EXHAUSTED = "lease_expired: the worker stopped during every attempt"
INTERNAL_ERROR = "internal_error: unexpected error while drafting"


@dataclass(frozen=True)
class GenerationPolicy:
    concurrency: int = 20
    lease_seconds: float = 120.0
    heartbeat_seconds: float = 40.0
    poll_seconds: float = 1.0
    max_attempts: int = 5
    backoff_base_seconds: float = 5.0
    backoff_cap_seconds: float = 300.0


class GenerationLoop:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        drafting: DraftingService,
        policy: GenerationPolicy,
    ) -> None:
        self._session_factory = session_factory
        self._drafting = drafting
        self._policy = policy
        self._in_flight: set[asyncio.Task[None]] = set()

    async def run(self, stop: asyncio.Event) -> None:
        stopping = asyncio.create_task(stop.wait())
        try:
            while not stop.is_set():
                free = self._policy.concurrency - len(self._in_flight)
                claimed = await self._claim(free) if free else []
                for ticket in claimed:
                    task = asyncio.create_task(self._process(ticket))
                    self._in_flight.add(task)
                    task.add_done_callback(self._forget)
                if claimed and len(claimed) == free:
                    continue
                await asyncio.wait(
                    [stopping, *self._in_flight],
                    timeout=self._policy.poll_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
        finally:
            stopping.cancel()
            # Leases of cancelled tickets expire and another worker takes them.
            for task in self._in_flight:
                task.cancel()
            await asyncio.gather(*self._in_flight, return_exceptions=True)

    def _forget(self, task: asyncio.Task[None]) -> None:
        self._in_flight.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Generation task crashed", exc_info=task.exception())

    async def _claim(self, limit: int) -> list[ClaimedTicket]:
        try:
            async with self._tickets() as tickets:
                return await tickets.claim_for_generation(
                    limit, self._policy.lease_seconds
                )
        except DatabaseUnavailableError:
            logger.warning("Database unavailable, generation claim skipped")
        except Exception:
            logger.exception("Generation claim failed")
        return []

    async def _process(self, ticket: ClaimedTicket) -> None:
        if ticket.attempt > self._policy.max_attempts:
            await self._fail(ticket, LEASE_EXHAUSTED)
            return
        heartbeat = asyncio.create_task(self._keep_lease(ticket))
        try:
            draft = await self._drafting.draft(ticket.message)
        except LLMRateLimitedError as error:
            await self._retry(ticket, describe(error), error.retry_after or 0.0)
        except TERMINAL_ERRORS as error:
            await self._fail(ticket, describe(error))
        except AppException as error:
            await self._retry(ticket, describe(error))
        except Exception:
            log(logging.ERROR, "Drafting failed unexpectedly", ticket, exc_info=True)
            await self._retry(ticket, INTERNAL_ERROR)
        else:
            await self._save(ticket, draft)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def _retry(
        self, ticket: ClaimedTicket, error: str, min_delay: float = 0.0
    ) -> None:
        if ticket.attempt >= self._policy.max_attempts:
            await self._fail(ticket, error)
            return
        delay = backoff_seconds(
            ticket.attempt,
            base=self._policy.backoff_base_seconds,
            cap=self._policy.backoff_cap_seconds,
        )
        await self._write(
            ticket,
            "retry",
            lambda tickets: tickets.retry_generation(
                ticket, delay_seconds=max(delay, min_delay), error=error
            ),
        )

    async def _fail(self, ticket: ClaimedTicket, error: str) -> None:
        await self._write(
            ticket,
            "generation_failed",
            lambda tickets: tickets.fail_generation(ticket, error=error),
        )

    async def _save(self, ticket: ClaimedTicket, draft: Draft) -> None:
        await self._write(
            ticket,
            "draft_ready",
            lambda tickets: tickets.save_draft(
                ticket,
                text=draft.text,
                sources=[source.model_dump() for source in draft.sources],
                low_confidence=draft.low_confidence,
                is_static=draft.is_static,
            ),
        )

    async def _write(
        self,
        ticket: ClaimedTicket,
        outcome: str,
        action: Callable[[TicketRepository], Awaitable[bool]],
    ) -> None:
        try:
            async with self._tickets() as tickets:
                written = await action(tickets)
        except DatabaseUnavailableError:
            log(logging.WARNING, "Database unavailable, result dropped", ticket)
            return
        if written:
            log(logging.INFO, f"Generation outcome: {outcome}", ticket)
        else:
            log(logging.WARNING, "Lease lost, result dropped", ticket)

    async def _keep_lease(self, ticket: ClaimedTicket) -> None:
        while True:
            await asyncio.sleep(self._policy.heartbeat_seconds)
            try:
                async with self._tickets() as tickets:
                    extended = await tickets.extend_generation_lease(
                        ticket, self._policy.lease_seconds
                    )
            except DatabaseUnavailableError:
                log(logging.WARNING, "Database unavailable, heartbeat missed", ticket)
                continue
            if not extended:
                log(logging.WARNING, "Lease lost during generation", ticket)
                return

    @asynccontextmanager
    async def _tickets(self) -> AsyncIterator[TicketRepository]:
        async with self._session_factory() as session:
            yield TicketRepositoryImpl(session)


def describe(error: AppException) -> str:
    details = ", ".join(f"{key}={value}" for key, value in error.payload.items())
    suffix = f" ({details})" if details else ""
    return f"{error.code}: {error.message}{suffix}"


def log(
    level: int, message: str, ticket: ClaimedTicket, *, exc_info: bool = False
) -> None:
    logger.log(
        level,
        message,
        exc_info=exc_info,
        extra={
            "event_id": ticket.event_id,
            "ticket_id": ticket.ticket_id,
            "attempt": ticket.attempt,
        },
    )
