import ast
import asyncio
import json
import math
import time
from collections import Counter
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from main import create_app
from tests.helpers import count_events, sample_event
from tickets.models import TicketEvent
from tickets.status import TicketStatus

WEBHOOK = "/webhooks/helpdesk"
SRC = Path(__file__).resolve().parents[1] / "src"
SLOW_COMPONENTS = {
    "llm",
    "drafting",
    "kb",
    "delivery",
    "workers",
    "httpx",
    "anthropic",
}


async def test_new_event_is_accepted_and_stored(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    event = sample_event(event_id="evt_8f2a")

    response = await db_client.post(WEBHOOK, json=event)

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    async with session_factory() as session:
        row = (await session.execute(select(TicketEvent))).scalar_one()
    assert row.event_id == "evt_8f2a"
    assert row.ticket_id == event["ticket_id"]
    assert row.customer_email == event["customer_email"]
    assert row.message == event["message"]
    assert row.reply_url == event["reply_url"]
    assert row.status == TicketStatus.RECEIVED
    assert row.gen_attempts == 0
    assert row.locked_until is None


async def test_repeated_event_is_reported_as_duplicate(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    event = sample_event()

    first = await db_client.post(WEBHOOK, json=event)
    second = await db_client.post(WEBHOOK, json=event)

    assert first.json() == {"status": "accepted"}
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate"}
    assert await count_events(session_factory) == 1


async def test_first_delivery_wins_when_a_duplicate_differs(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    event = sample_event(message="original message")
    await db_client.post(WEBHOOK, json=event)

    await db_client.post(WEBHOOK, json={**event, "message": "changed message"})

    async with session_factory() as session:
        row = (await session.execute(select(TicketEvent))).scalar_one()
    assert row.message == "original message"


async def test_concurrent_duplicates_create_exactly_one_row(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    event = sample_event()

    responses = await asyncio.gather(
        *(db_client.post(WEBHOOK, json=event) for _ in range(50))
    )

    assert {response.status_code for response in responses} == {200}
    statuses = Counter(response.json()["status"] for response in responses)
    assert statuses == {"accepted": 1, "duplicate": 49}
    assert await count_events(session_factory) == 1


async def test_concurrent_distinct_events_are_all_stored(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    events = [sample_event() for _ in range(40)]

    responses = await asyncio.gather(
        *(db_client.post(WEBHOOK, json=event) for event in events)
    )

    assert {response.json()["status"] for response in responses} == {"accepted"}
    assert await count_events(session_factory) == 40


async def test_follow_up_event_on_the_same_ticket_is_a_new_row(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await db_client.post(WEBHOOK, json=sample_event(ticket_id="T-7"))
    await db_client.post(WEBHOOK, json=sample_event(ticket_id="T-7"))

    assert await count_events(session_factory) == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"event_id": ""},
        {"ticket_id": ""},
        {"customer_email": "not-an-email"},
        {"message": ""},
        {"message": "x" * 20_001},
        {"reply_url": "not a url"},
        {"reply_url": "ftp://helpdesk.example.com/replies"},
        {"event_id": "   "},
        {"message": "   "},
        {"message": "a\u0000b"},
        {"event_id": "evt\u0000"},
        {"ticket_id": "T-1\u0000"},
        {"customer_email": "user@example.com\u0000"},
    ],
)
async def test_invalid_body_is_rejected_and_nothing_is_stored(
    db_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    overrides: dict[str, str],
) -> None:
    response = await db_client.post(WEBHOOK, json=sample_event(**overrides))

    assert response.status_code == 422
    assert await count_events(session_factory) == 0


@pytest.mark.parametrize(
    "missing", ["event_id", "ticket_id", "customer_email", "message", "reply_url"]
)
async def test_missing_field_is_rejected(db_client: AsyncClient, missing: str) -> None:
    event = sample_event()
    del event[missing]

    response = await db_client.post(WEBHOOK, json=event)

    assert response.status_code == 422


async def test_body_that_is_not_json_is_rejected(db_client: AsyncClient) -> None:
    response = await db_client.post(
        WEBHOOK, content="nope", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422


def test_webhook_code_does_not_depend_on_slow_components() -> None:
    imported: set[str] = set()
    for package in ("webhooks", "tickets"):
        for path in (SRC / package).glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])

    assert imported.isdisjoint(SLOW_COMPONENTS)


async def test_webhook_answers_fast(db_client: AsyncClient) -> None:
    durations = []
    for _ in range(30):
        started = time.perf_counter()
        response = await db_client.post(WEBHOOK, json=sample_event())
        durations.append(time.perf_counter() - started)
        assert response.status_code == 200

    durations.sort()
    assert durations[math.ceil(len(durations) * 0.95) - 1] < 0.2


async def test_row_is_committed_before_the_response_starts(
    db_app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    event = sample_event()
    body = json.dumps(event).encode()
    visible_when_response_starts: list[bool] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict) -> None:
        if message["type"] != "http.response.start":
            return
        async with session_factory() as session:
            found = await session.scalar(
                select(TicketEvent.id).where(TicketEvent.event_id == event["event_id"])
            )
        visible_when_response_starts.append(found is not None)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": WEBHOOK,
        "raw_path": WEBHOOK.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
    }

    await db_app(scope, receive, send)

    assert visible_when_response_starts == [True]


async def test_event_survives_an_application_restart(
    db_app: FastAPI, db_client: AsyncClient, migrated_schema: str
) -> None:
    await db_client.post(WEBHOOK, json=sample_event())
    await db_app.state.db_engine.dispose()

    restarted = create_app(Settings(_env_file=None, DATABASE_URL=migrated_schema))
    transport = ASGITransport(app=restarted, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        stats = await http.get("/api/stats")
    await restarted.state.db_engine.dispose()

    assert stats.json()["counts"]["received"] == 1


@pytest.mark.parametrize(
    "unreachable_url",
    [
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:1/helpdesk",
        "postgresql+asyncpg://postgres:postgres@no-such-host.invalid:5432/helpdesk",
    ],
)
async def test_unavailable_database_answers_503_so_the_helpdesk_retries(
    unreachable_url: str,
) -> None:
    broken = create_app(Settings(_env_file=None, DATABASE_URL=unreachable_url))
    transport = ASGITransport(app=broken, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post(WEBHOOK, json=sample_event())
    await broken.state.db_engine.dispose()

    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
