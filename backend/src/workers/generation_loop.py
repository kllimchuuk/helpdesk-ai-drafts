import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions import AppException, DatabaseUnavailableError
from drafting.schemas import Draft
from drafting.service import DraftingService
from llm.exceptions import LLMRateLimitedError, LLMRefusalError, LLMRejectedError
from tickets.repository import TicketRepository
from tickets.schemas import ClaimedTicket
from tickets.service import claimed_ticket
from workers.backoff import backoff_seconds
from workers.queue_loop import QueueLoop, log

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


class GenerationLoop(QueueLoop[ClaimedTicket]):
    name = "Generation"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        drafting: DraftingService,
        policy: GenerationPolicy,
    ) -> None:
        super().__init__(
            session_factory,
            concurrency=policy.concurrency,
            poll_seconds=policy.poll_seconds,
        )
        self._drafting = drafting
        self._policy = policy

    async def _claim_batch(
        self, tickets: TicketRepository, limit: int
    ) -> list[ClaimedTicket]:
        rows = await tickets.claim_for_generation(limit, self._policy.lease_seconds)
        return [claimed_ticket(row) for row in rows]

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
            except Exception:
                log(logging.ERROR, "Heartbeat failed", ticket, exc_info=True)
                continue
            if not extended:
                log(logging.WARNING, "Lease lost during generation", ticket)
                return


def describe(error: AppException) -> str:
    details = ", ".join(f"{key}={value}" for key, value in error.payload.items())
    suffix = f" ({details})" if details else ""
    return f"{error.code}: {error.message}{suffix}"
