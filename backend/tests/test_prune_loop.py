import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from llm.models import LlmCall
from llm.repository import LlmCallRepositoryImpl
from llm.route import LlmRoute
from tests.helpers import sample_event
from tickets.models import TicketEvent
from tickets.repository import TicketRepositoryImpl
from tickets.status import TicketStatus
from workers.dependencies import build_prune_loop
from workers.prune_loop import FINISHED_STATUSES, PruneLoop, PrunePolicy

DAY = 86_400.0
POLICY = PrunePolicy(
    ticket_retention_seconds=30 * DAY,
    llm_call_retention_seconds=2 * DAY,
    interval_seconds=0.05,
)


async def seed_ticket(
    session_factory: async_sessionmaker[AsyncSession],
    event_id: str,
    status: TicketStatus,
    age_days: int,
) -> None:
    async with session_factory() as session:
        await TicketRepositoryImpl(session).insert_if_new(
            **sample_event(event_id=event_id)
        )
        await session.execute(
            update(TicketEvent)
            .where(TicketEvent.event_id == event_id)
            .values(status=status, updated_at=func.now() - timedelta(days=age_days))
        )
        await session.commit()


async def seed_call(
    session_factory: async_sessionmaker[AsyncSession], age_days: int
) -> None:
    async with session_factory() as session:
        await LlmCallRepositoryImpl(session).record(LlmRoute.PROVIDER)
        await session.execute(
            update(LlmCall)
            .where(LlmCall.id == select(func.max(LlmCall.id)).scalar_subquery())
            .values(called_at=func.clock_timestamp() - timedelta(days=age_days))
        )
        await session.commit()


async def event_ids(session_factory: async_sessionmaker[AsyncSession]) -> set[str]:
    async with session_factory() as session:
        return set(await session.scalars(select(TicketEvent.event_id)))


async def call_count(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(LlmCall))


async def clean(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await session.execute(text("TRUNCATE ticket_events, llm_calls"))
        await session.commit()


async def test_only_old_finished_tickets_are_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await clean(session_factory)
    await seed_ticket(session_factory, "old-sent", TicketStatus.SENT, 31)
    await seed_ticket(session_factory, "old-rejected", TicketStatus.REJECTED, 31)
    await seed_ticket(session_factory, "new-sent", TicketStatus.SENT, 1)
    await seed_ticket(session_factory, "old-unknown", TicketStatus.SEND_UNKNOWN, 31)
    await seed_ticket(session_factory, "old-draft", TicketStatus.DRAFT_READY, 31)
    await seed_ticket(session_factory, "old-received", TicketStatus.RECEIVED, 31)

    async with session_factory() as session:
        deleted = await TicketRepositoryImpl(session).delete_finished_older_than(
            list(FINISHED_STATUSES), 30 * DAY
        )

    assert deleted == 2
    assert await event_ids(session_factory) == {
        "new-sent",
        "old-unknown",
        "old-draft",
        "old-received",
    }


async def test_old_llm_calls_are_deleted_and_recent_ones_stay(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await clean(session_factory)
    await seed_call(session_factory, 3)
    await seed_call(session_factory, 3)
    await seed_call(session_factory, 0)

    async with session_factory() as session:
        deleted = await LlmCallRepositoryImpl(session).delete_older_than(2 * DAY)

    assert deleted == 2
    assert await call_count(session_factory) == 1


async def test_the_loop_prunes_both_tables_and_stops_on_request(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await clean(session_factory)
    await seed_ticket(session_factory, "old-sent", TicketStatus.SENT, 40)
    await seed_ticket(session_factory, "new-sent", TicketStatus.SENT, 0)
    await seed_call(session_factory, 5)
    stop = asyncio.Event()
    task = asyncio.create_task(PruneLoop(session_factory, POLICY).run(stop))

    for _ in range(100):
        if await event_ids(session_factory) == {"new-sent"} and not await call_count(
            session_factory
        ):
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=5)

    assert await event_ids(session_factory) == {"new-sent"}
    assert await call_count(session_factory) == 0


async def test_a_failing_prune_does_not_stop_the_loop(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await clean(session_factory)
    stop = asyncio.Event()
    loop = PruneLoop(session_factory, POLICY)
    calls = 0

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")

    loop.prune_once = flaky
    task = asyncio.create_task(loop.run(stop))

    for _ in range(100):
        if calls >= 2:
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=5)

    assert calls >= 2


def test_only_the_four_finished_statuses_are_pruned() -> None:
    assert set(FINISHED_STATUSES) == {
        TicketStatus.SENT,
        TicketStatus.REJECTED,
        TicketStatus.GENERATION_FAILED,
        TicketStatus.SEND_FAILED,
    }


@pytest.mark.parametrize("status", list(TicketStatus))
async def test_an_old_ticket_is_deleted_only_when_its_status_is_finished(
    session_factory: async_sessionmaker[AsyncSession], status: TicketStatus
) -> None:
    await clean(session_factory)
    await seed_ticket(session_factory, "old", status, 31)

    await PruneLoop(session_factory, POLICY).prune_once()

    expected = set() if status in FINISHED_STATUSES else {"old"}
    assert await event_ids(session_factory) == expected


async def test_retention_days_reach_the_loop_as_days(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await clean(session_factory)
    await seed_ticket(session_factory, "day-29", TicketStatus.SENT, 29)
    await seed_ticket(session_factory, "day-31", TicketStatus.SENT, 31)

    await build_prune_loop(
        Settings(_env_file=None, RETENTION_DAYS=30), session_factory
    ).prune_once()

    assert await event_ids(session_factory) == {"day-29"}


async def test_the_repositories_commit_their_own_deletes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await clean(session_factory)
    await seed_ticket(session_factory, "old-sent", TicketStatus.SENT, 40)
    await seed_call(session_factory, 5)

    async with session_factory() as session:
        await TicketRepositoryImpl(session).delete_finished_older_than(
            list(FINISHED_STATUSES), 30 * DAY
        )
    async with session_factory() as session:
        await LlmCallRepositoryImpl(session).delete_older_than(2 * DAY)

    assert await event_ids(session_factory) == set()
    assert await call_count(session_factory) == 0
