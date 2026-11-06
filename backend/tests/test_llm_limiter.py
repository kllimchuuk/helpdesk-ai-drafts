import asyncio
from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import build_engine, build_session_factory
from llm.limiter import RateLimiter
from llm.repository import LlmCallRepositoryImpl
from llm.route import LlmRoute
from llm.service import LlmCallService

WINDOW = 60.0


def limiter(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int = 5,
    window: float = WINDOW,
    daily_cap: int = 100,
    has_key: bool = True,
    slept: list[float] | None = None,
) -> RateLimiter:
    async def record_sleep(seconds: float) -> None:
        if slept is not None:
            slept.append(seconds)
        await asyncio.sleep(seconds)

    return RateLimiter(
        session_factory,
        limit=limit,
        window_seconds=window,
        daily_cap=daily_cap,
        has_key=has_key,
        sleep=record_sleep,
        jitter_seconds=0,
    )


async def reserve_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int = 5,
    window: float = WINDOW,
    daily_cap: int = 100,
    has_key: bool = True,
):
    async with session_factory() as session:
        service = LlmCallService(
            LlmCallRepositoryImpl(session),
            limit=limit,
            window_seconds=window,
            daily_cap=daily_cap,
            has_key=has_key,
        )
        return await service.reserve()


async def insert_calls(
    session_factory: async_sessionmaker[AsyncSession],
    kind: str,
    age: str,
    count: int = 1,
) -> None:
    async with session_factory() as session:
        for _ in range(count):
            await session.execute(
                text(
                    "INSERT INTO llm_calls (kind, called_at) "
                    f"VALUES (:kind, clock_timestamp() - interval '{age}')"
                ),
                {"kind": kind},
            )
        await session.commit()


async def stored_calls(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[tuple[str, datetime]]:
    async with session_factory() as session:
        rows = await session.execute(
            text("SELECT kind, called_at FROM llm_calls ORDER BY called_at")
        )
        return [(row.kind, row.called_at) for row in rows]


async def test_a_call_below_the_limit_is_granted_and_recorded(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    reservation = await reserve_once(session_factory)

    assert reservation.route == LlmRoute.PROVIDER
    assert [kind for kind, _ in await stored_calls(session_factory)] == ["provider"]


async def test_a_full_window_answers_with_a_wait_and_records_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_calls(session_factory, "provider", "10 seconds", count=3)

    reservation = await reserve_once(session_factory, limit=3)

    assert reservation.route is None
    assert 45 < reservation.wait_seconds <= 50
    assert len(await stored_calls(session_factory)) == 3


async def test_the_wait_ends_when_the_oldest_call_leaves_the_window(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_calls(session_factory, "provider", "50 seconds")
    await insert_calls(session_factory, "provider", "5 seconds", count=2)

    reservation = await reserve_once(session_factory, limit=3)

    assert reservation.route is None
    assert 0 < reservation.wait_seconds <= 10


async def test_the_wait_covers_calls_above_the_limit_after_it_was_lowered(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    for age in ("50 seconds", "40 seconds", "30 seconds", "20 seconds", "10 seconds"):
        await insert_calls(session_factory, "provider", age)

    reservation = await reserve_once(session_factory, limit=3)

    assert reservation.route is None
    assert 25 < reservation.wait_seconds <= 30


async def test_calls_older_than_the_window_do_not_count(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_calls(session_factory, "provider", "61 seconds", count=5)

    reservation = await reserve_once(session_factory, limit=5)

    assert reservation.route == LlmRoute.PROVIDER


async def test_keyless_calls_count_towards_the_rate_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_calls(session_factory, "keyless", "1 second", count=3)

    reservation = await reserve_once(session_factory, limit=3)

    assert reservation.route is None


async def test_the_limiter_waits_and_then_takes_the_freed_slot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_calls(session_factory, "provider", "0.3 seconds", count=2)
    slept: list[float] = []

    route = await limiter(session_factory, limit=2, window=0.5, slept=slept).acquire()

    assert route == LlmRoute.PROVIDER
    assert len(slept) >= 1
    assert sum(slept) <= 0.5
    assert len(await stored_calls(session_factory)) == 3


async def test_no_window_ever_holds_more_calls_than_the_limit_across_workers(
    migrated_schema: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    limit, window, workers, rounds = 3, 0.4, 6, 3
    engines = [build_engine(migrated_schema) for _ in range(workers)]
    try:
        limiters = [
            limiter(build_session_factory(engine), limit=limit, window=window)
            for engine in engines
        ]

        async def work(worker: RateLimiter) -> None:
            for _ in range(rounds):
                await worker.acquire()

        await asyncio.gather(*(work(worker) for worker in limiters))
    finally:
        for engine in engines:
            await engine.dispose()

    times = [called_at for _, called_at in await stored_calls(session_factory)]
    assert len(times) == workers * rounds
    for start in times:
        in_window = [
            moment for moment in times if 0 <= (moment - start).total_seconds() < window
        ]
        assert len(in_window) <= limit


async def test_provider_calls_stop_at_the_daily_cap(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    routes = [
        (await reserve_once(session_factory, limit=100, daily_cap=3)).route
        for _ in range(5)
    ]

    assert routes == [
        LlmRoute.PROVIDER,
        LlmRoute.PROVIDER,
        LlmRoute.PROVIDER,
        LlmRoute.KEYLESS,
        LlmRoute.KEYLESS,
    ]


async def test_keyless_calls_do_not_use_up_the_daily_cap(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_calls(session_factory, "keyless", "1 second", count=10)

    reservation = await reserve_once(session_factory, limit=100, daily_cap=3)

    assert reservation.route == LlmRoute.PROVIDER


async def test_yesterdays_provider_calls_do_not_use_up_the_daily_cap(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO llm_calls (kind, called_at) SELECT 'provider', "
                "date_trunc('day', clock_timestamp() AT TIME ZONE 'UTC') "
                "AT TIME ZONE 'UTC' - interval '1 hour' FROM generate_series(1, 3)"
            )
        )
        await session.commit()

    reservation = await reserve_once(session_factory, limit=100, daily_cap=3)

    assert reservation.route == LlmRoute.PROVIDER


async def test_todays_provider_calls_count_whatever_the_window(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_calls(session_factory, "provider", "1 second", count=3)

    reservation = await reserve_once(
        session_factory, limit=100, window=0.1, daily_cap=3
    )

    assert reservation.route == LlmRoute.KEYLESS


async def test_without_a_key_every_call_is_keyless(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    reservation = await reserve_once(session_factory, has_key=False)

    assert reservation.route == LlmRoute.KEYLESS
    assert [kind for kind, _ in await stored_calls(session_factory)] == ["keyless"]


@pytest.mark.parametrize("kind", ["manual", ""])
async def test_the_database_rejects_an_unknown_kind(
    session_factory: async_sessionmaker[AsyncSession], kind: str
) -> None:
    with pytest.raises(Exception, match="ck_llm_calls_kind"):
        await insert_calls(session_factory, kind, "1 second")
