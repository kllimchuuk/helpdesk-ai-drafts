import asyncio
import time

import httpx2
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from llm.keyless import STATIC_REPLY
from tests.helpers import sample_event
from tickets.models import TicketEvent
from tickets.repository import TicketRepositoryImpl
from tickets.status import TicketStatus
from workers.runner import run_worker

WAIT_LIMIT_S = 15.0


def unauthorized(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        401,
        json={"type": "error", "error": {"type": "authentication_error"}},
    )


async def test_without_a_key_the_worker_stores_a_static_draft(
    migrated_schema: str,
    session_factory: async_sessionmaker[AsyncSession],
    loaded_kb: None,
) -> None:
    """I8 through the real wiring: limiter, keyless client, drafting, queue."""
    async with session_factory() as session:
        await TicketRepositoryImpl(session).insert_if_new(**sample_event())
    requests: list[httpx2.Request] = []

    def provider(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return unauthorized(request)

    settings = Settings(
        _env_file=None,
        DATABASE_URL=migrated_schema,
        ANTHROPIC_API_KEY=SecretStr(""),
        KEYLESS_DELAY_MIN_S=1,
        KEYLESS_DELAY_MAX_S=1,
        PUBLIC_BASE_URL="https://drafts.example.com",
    )
    stop = asyncio.Event()
    started = time.monotonic()
    worker = asyncio.create_task(
        run_worker(
            settings,
            stop,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(provider)),
        )
    )
    try:
        row = await wait_for_draft(session_factory)
    finally:
        stop.set()
        await asyncio.wait_for(worker, timeout=5)
    elapsed = time.monotonic() - started

    assert row.draft_is_static is True
    assert row.draft_text.startswith(STATIC_REPLY)
    assert "https://drafts.example.com/kb/export-report-pdf" in row.draft_text
    assert len(requests) == 1
    assert elapsed >= 1
    async with session_factory() as session:
        kinds = list(await session.scalars(text("SELECT kind FROM llm_calls")))
    assert kinds == ["keyless"]


async def wait_for_draft(
    session_factory: async_sessionmaker[AsyncSession],
) -> TicketEvent:
    deadline = time.monotonic() + WAIT_LIMIT_S
    while time.monotonic() < deadline:
        async with session_factory() as session:
            row = await session.scalar(select(TicketEvent))
        if row.status == TicketStatus.DRAFT_READY:
            return row
        await asyncio.sleep(0.1)
    raise AssertionError(f"timed out in status {row.status}")
