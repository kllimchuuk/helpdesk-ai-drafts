import asyncio
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import build_engine, build_session_factory
from drafting.service import DraftingService
from llm.client import LLMClient
from llm.exceptions import (
    LLMInvalidOutputError,
    LLMRateLimitedError,
    LLMRefusalError,
    LLMRejectedError,
    LLMTransientError,
)
from llm.schemas import LLMRequest, LLMResult
from tests.fakes import FakeLLMClient, HangingLLMClient
from tests.helpers import sample_event
from tickets.models import TicketEvent
from tickets.repository import TicketRepositoryImpl
from tickets.status import TicketStatus
from workers.generation_loop import (
    LEASE_EXHAUSTED,
    GenerationLoop,
    GenerationPolicy,
)

PDF_TICKET = "Не можу експортувати звіт у PDF"
FAST = GenerationPolicy(
    concurrency=5,
    lease_seconds=1.0,
    heartbeat_seconds=0.2,
    poll_seconds=0.05,
    max_attempts=5,
    backoff_base_seconds=0.01,
    backoff_cap_seconds=0.05,
)
WAIT_LIMIT_S = 15.0


class Worker:
    """A generation loop running in the background, as one worker process."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm: LLMClient,
        policy: GenerationPolicy = FAST,
    ) -> None:
        drafting = DraftingService(
            session_factory, llm, min_score=0.4, public_base_url="http://kb"
        )
        self.stop = asyncio.Event()
        self.task = asyncio.create_task(
            GenerationLoop(session_factory, drafting, policy).run(self.stop)
        )

    async def shutdown(self) -> None:
        self.stop.set()
        await asyncio.wait_for(self.task, timeout=5)

    async def kill(self) -> None:
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


async def insert_events(
    session_factory: async_sessionmaker[AsyncSession],
    count: int = 1,
    message: str = PDF_TICKET,
) -> None:
    async with session_factory() as session:
        repository = TicketRepositoryImpl(session)
        for _ in range(count):
            await repository.insert_if_new(**sample_event(message=message))


async def rows(session_factory: async_sessionmaker[AsyncSession]) -> list[TicketEvent]:
    async with session_factory() as session:
        return list(await session.scalars(select(TicketEvent)))


async def wait_until(
    session_factory: async_sessionmaker[AsyncSession],
    condition: Callable[[list[TicketEvent]], bool],
) -> list[TicketEvent]:
    deadline = time.monotonic() + WAIT_LIMIT_S
    while time.monotonic() < deadline:
        current = await rows(session_factory)
        if condition(current):
            return current
        await asyncio.sleep(0.05)
    raise AssertionError(f"timed out: {[(r.status, r.gen_attempts) for r in current]}")


def all_in(*statuses: TicketStatus) -> Callable[[list[TicketEvent]], bool]:
    return lambda found: bool(found) and all(row.status in statuses for row in found)


async def run_to_end(
    session_factory: async_sessionmaker[AsyncSession],
    llm: LLMClient,
    policy: GenerationPolicy = FAST,
) -> list[TicketEvent]:
    worker = Worker(session_factory, llm, policy)
    try:
        return await wait_until(
            session_factory,
            all_in(TicketStatus.DRAFT_READY, TicketStatus.GENERATION_FAILED),
        )
    finally:
        await worker.shutdown()


async def test_received_tickets_become_drafts(
    session_factory: async_sessionmaker[AsyncSession], loaded_kb: None
) -> None:
    await insert_events(session_factory, 3)
    llm = FakeLLMClient(
        default=LLMResult(
            reply="Відкрийте звіт.", cited_slugs=["export-report-pdf"], is_static=False
        )
    )

    found = await run_to_end(session_factory, llm)

    assert len(llm.requests) == 3
    for row in found:
        assert row.status == TicketStatus.DRAFT_READY
        assert row.draft_text.startswith("Відкрийте звіт.\n\n")
        assert row.draft_sources == [
            {
                "slug": "export-report-pdf",
                "title": "Експорт звіту в PDF",
                "url": "http://kb/kb/export-report-pdf",
            }
        ]
        assert row.low_confidence is False
        assert row.draft_is_static is False
        assert row.gen_attempts == 1
        assert row.locked_until is None
        assert row.last_error is None


async def test_a_static_reply_is_stored_as_static(
    session_factory: async_sessionmaker[AsyncSession], loaded_kb: None
) -> None:
    await insert_events(session_factory)
    llm = FakeLLMClient(default=LLMResult("Static.", [], is_static=True))

    [row] = await run_to_end(session_factory, llm)

    assert row.status == TicketStatus.DRAFT_READY
    assert row.draft_is_static is True


async def test_transient_errors_are_retried_until_a_draft_arrives(
    session_factory: async_sessionmaker[AsyncSession], loaded_kb: None
) -> None:
    await insert_events(session_factory)
    llm = FakeLLMClient(LLMTransientError("HTTP 503"), LLMTransientError("timeout"))

    [row] = await run_to_end(session_factory, llm)

    assert row.status == TicketStatus.DRAFT_READY
    assert row.gen_attempts == 3
    assert row.last_error is None


async def test_invalid_model_output_is_retried(
    session_factory: async_sessionmaker[AsyncSession], loaded_kb: None
) -> None:
    await insert_events(session_factory)
    llm = FakeLLMClient(LLMInvalidOutputError("the answer was cut off"))

    [row] = await run_to_end(session_factory, llm)

    assert row.status == TicketStatus.DRAFT_READY
    assert row.gen_attempts == 2


async def test_a_refusal_fails_the_ticket_without_a_retry(
    session_factory: async_sessionmaker[AsyncSession], loaded_kb: None
) -> None:
    await insert_events(session_factory)
    llm = FakeLLMClient(LLMRefusalError())

    [row] = await run_to_end(session_factory, llm)

    assert row.status == TicketStatus.GENERATION_FAILED
    assert row.gen_attempts == 1
    assert row.last_error.startswith("llm_refusal: ")
    assert len(llm.requests) == 1


async def test_a_rejected_request_fails_the_ticket_with_the_status(
    session_factory: async_sessionmaker[AsyncSession], loaded_kb: None
) -> None:
    await insert_events(session_factory)
    llm = FakeLLMClient(LLMRejectedError(400))

    [row] = await run_to_end(session_factory, llm)

    assert row.status == TicketStatus.GENERATION_FAILED
    assert row.last_error.startswith("llm_request_rejected: ")
    assert row.last_error.endswith("(status=400)")


async def test_a_ticket_fails_after_the_attempt_cap(
    session_factory: async_sessionmaker[AsyncSession], loaded_kb: None
) -> None:
    await insert_events(session_factory)
    llm = FakeLLMClient(*(LLMTransientError("HTTP 503") for _ in range(10)))

    [row] = await run_to_end(session_factory, llm)

    assert row.status == TicketStatus.GENERATION_FAILED
    assert row.gen_attempts == FAST.max_attempts
    assert len(llm.requests) == FAST.max_attempts
    assert row.last_error.startswith("llm_unavailable: ")


async def test_an_unexpected_error_is_retried_and_does_not_stop_the_loop(
    session_factory: async_sessionmaker[AsyncSession], loaded_kb: None
) -> None:
    await insert_events(session_factory, 2)
    llm = FakeLLMClient(RuntimeError("bug"))
    # A lease far longer than the wait: only the explicit retry can bring the
    # ticket back in time, not the expiry of a crashed task's lease.
    policy = replace(FAST, lease_seconds=600.0)

    found = await run_to_end(session_factory, llm, policy)

    assert [row.status for row in found] == [TicketStatus.DRAFT_READY] * 2
    assert sorted(row.gen_attempts for row in found) == [1, 2]


async def test_retry_after_from_the_provider_postpones_the_next_attempt(
    session_factory: async_sessionmaker[AsyncSession], loaded_kb: None
) -> None:
    await insert_events(session_factory)
    worker = Worker(session_factory, FakeLLMClient(LLMRateLimitedError(60.0)))
    try:
        [row] = await wait_until(
            session_factory, lambda found: found[0].last_error is not None
        )
    finally:
        await worker.shutdown()

    assert row.status == TicketStatus.RECEIVED
    assert row.next_attempt_at - row.updated_at >= timedelta(seconds=60)
    assert row.last_error.startswith("llm_rate_limited: ")


async def test_concurrency_is_bounded_by_the_policy(
    session_factory: async_sessionmaker[AsyncSession], loaded_kb: None
) -> None:
    await insert_events(session_factory, 12)
    running = 0
    peak = 0

    async def track(_request: LLMRequest) -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.1)
        running -= 1

    found = await run_to_end(session_factory, FakeLLMClient(on_call=track))

    assert len(found) == 12
    assert peak == FAST.concurrency


async def test_two_workers_draft_every_ticket_exactly_once(
    session_factory: async_sessionmaker[AsyncSession], loaded_kb: None
) -> None:
    await insert_events(session_factory, 30)
    first = FakeLLMClient(delay=0.02)
    second = FakeLLMClient(delay=0.02)
    workers = [Worker(session_factory, first), Worker(session_factory, second)]
    try:
        found = await wait_until(session_factory, all_in(TicketStatus.DRAFT_READY))
    finally:
        await asyncio.gather(*(worker.shutdown() for worker in workers))

    assert len(first.requests) + len(second.requests) == 30
    assert first.requests and second.requests
    assert all(row.gen_attempts == 1 for row in found)


async def test_a_worker_killed_mid_generation_does_not_strand_the_ticket(
    session_factory: async_sessionmaker[AsyncSession], loaded_kb: None
) -> None:
    """I5: the lease expires and another worker finishes the ticket."""
    await insert_events(session_factory)
    hanging = HangingLLMClient()
    crashed = Worker(session_factory, hanging)
    await asyncio.wait_for(hanging.started.wait(), timeout=5)
    await crashed.kill()

    [row] = await rows(session_factory)
    assert row.status == TicketStatus.GENERATING

    [row] = await run_to_end(session_factory, FakeLLMClient())

    assert row.status == TicketStatus.DRAFT_READY
    assert row.gen_attempts == 2


async def test_the_heartbeat_keeps_a_slow_ticket_with_its_worker(
    session_factory: async_sessionmaker[AsyncSession], loaded_kb: None
) -> None:
    await insert_events(session_factory)
    hanging = HangingLLMClient()
    slow = Worker(session_factory, hanging)
    await asyncio.wait_for(hanging.started.wait(), timeout=5)
    other_llm = FakeLLMClient()
    other = Worker(session_factory, other_llm)
    try:
        await asyncio.sleep(FAST.lease_seconds * 3)
        [row] = await rows(session_factory)
        assert row.status == TicketStatus.GENERATING
        assert other_llm.requests == []
    finally:
        await slow.kill()
        await other.shutdown()


async def test_a_ticket_whose_worker_died_on_every_attempt_fails_without_a_call(
    session_factory: async_sessionmaker[AsyncSession], loaded_kb: None
) -> None:
    await insert_events(session_factory)
    async with session_factory() as session:
        await session.execute(
            update(TicketEvent).values(
                status=TicketStatus.GENERATING,
                gen_attempts=FAST.max_attempts,
                locked_until=func.now() - timedelta(seconds=1),
            )
        )
        await session.commit()
    llm = FakeLLMClient()

    [row] = await run_to_end(session_factory, llm)

    assert row.status == TicketStatus.GENERATION_FAILED
    assert row.last_error == LEASE_EXHAUSTED
    assert llm.requests == []


async def test_acknowledged_tickets_survive_a_restart_of_every_process(
    migrated_schema: str,
    session_factory: async_sessionmaker[AsyncSession],
    loaded_kb: None,
) -> None:
    """I3: events in flight when the workers die all reach a draft after restart."""
    await insert_events(session_factory, 8)
    hanging = HangingLLMClient()
    engine = build_engine(migrated_schema)
    crashed = Worker(build_session_factory(engine), hanging)
    await asyncio.wait_for(hanging.started.wait(), timeout=5)
    await crashed.kill()
    await engine.dispose()

    restarted_engine = build_engine(migrated_schema)
    try:
        found = await run_to_end(
            build_session_factory(restarted_engine), FakeLLMClient()
        )
    finally:
        await restarted_engine.dispose()

    assert len(found) == 8
    assert all(row.status == TicketStatus.DRAFT_READY for row in found)


async def test_the_loop_survives_a_failed_claim(
    session_factory: async_sessionmaker[AsyncSession],
    loaded_kb: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await insert_events(session_factory)
    real_claim = TicketRepositoryImpl.claim_for_generation
    calls = 0

    async def flaky_claim(self, limit: int, lease: float):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("claim broke")
        return await real_claim(self, limit, lease)

    monkeypatch.setattr(TicketRepositoryImpl, "claim_for_generation", flaky_claim)

    [row] = await run_to_end(session_factory, FakeLLMClient())

    assert calls >= 2
    assert row.status == TicketStatus.DRAFT_READY


async def test_a_result_that_cannot_be_written_is_logged_with_the_ticket(
    session_factory: async_sessionmaker[AsyncSession],
    loaded_kb: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await insert_events(session_factory)
    [event] = await rows(session_factory)

    async def broken_save(self, ticket, **values) -> bool:
        raise RuntimeError("cannot store")

    monkeypatch.setattr(TicketRepositoryImpl, "save_draft", broken_save)
    worker = Worker(session_factory, FakeLLMClient())
    try:
        await wait_until(session_factory, lambda found: found[0].gen_attempts == 1)
        deadline = time.monotonic() + WAIT_LIMIT_S
        while not any(hasattr(r, "event_id") for r in caplog.records):
            assert time.monotonic() < deadline
            await asyncio.sleep(0.05)
    finally:
        await worker.shutdown()

    [record] = [r for r in caplog.records if r.levelname == "ERROR"]
    assert record.event_id == event.event_id
    assert record.ticket_id == event.ticket_id
    assert record.exc_info is not None
