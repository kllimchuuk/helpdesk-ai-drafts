import asyncio
import json
import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

import httpx
from httpx import AsyncClient
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.database import build_session_factory
from delivery.helpdesk_client import HelpdeskClient, build_http_client
from tests.fakes import FakeHelpdesk, resolve_to
from tests.helpers import sample_event
from tickets.models import TicketEvent
from tickets.status import TicketStatus
from workers.send_loop import INTERNAL_ERROR, STALE_SEND_ERROR, SendLoop, SendPolicy

PUBLIC_IP = "93.184.216.34"
FAST = SendPolicy(
    concurrency=5,
    lease_seconds=1.0,
    poll_seconds=0.05,
    max_attempts=8,
    backoff_base_seconds=0.01,
    backoff_cap_seconds=0.02,
)
WAIT_LIMIT_S = 15.0
SETTLED = {TicketStatus.SENT, TicketStatus.SEND_UNKNOWN, TicketStatus.SEND_FAILED}
OPERATOR = {
    "auth": ("operator", "operator"),
    "headers": {"X-Requested-By": "operator-ui", "Content-Type": "application/json"},
}


class Sender:
    """A send loop running in the background, as one worker process."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        helpdesk: Callable,
        policy: SendPolicy = FAST,
        resolve=None,
    ) -> None:
        self.http = build_http_client(httpx.MockTransport(helpdesk))
        client = HelpdeskClient(
            self.http,
            allowed_hosts=frozenset(),
            resolve=resolve or resolve_to(PUBLIC_IP),
        )
        self.stop = asyncio.Event()
        self.task = asyncio.create_task(
            SendLoop(session_factory, client, policy).run(self.stop)
        )

    async def shutdown(self) -> None:
        self.stop.set()
        await asyncio.wait_for(self.task, timeout=5)
        await self.http.aclose()

    async def kill(self) -> None:
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        await self.http.aclose()


async def approved_tickets(
    session_factory: async_sessionmaker[AsyncSession], count: int = 1
) -> list[uuid.UUID]:
    rows = []
    async with session_factory() as session:
        for index in range(count):
            event = sample_event(ticket_id=f"T-{index}")
            row = TicketEvent(
                **event,
                status=TicketStatus.APPROVED,
                draft_text=f"Reply {index}",
            )
            session.add(row)
            rows.append(row)
        await session.commit()
    return [row.id for row in rows]


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
    raise AssertionError(f"timed out: {Counter(row.status for row in current)}")


def all_settled(found: list[TicketEvent]) -> bool:
    return bool(found) and all(row.status in SETTLED for row in found)


async def run_to_end(
    session_factory: async_sessionmaker[AsyncSession],
    helpdesk: Callable,
    policy: SendPolicy = FAST,
    resolve=None,
) -> list[TicketEvent]:
    sender = Sender(session_factory, helpdesk, policy, resolve)
    try:
        return await wait_until(session_factory, all_settled)
    finally:
        await sender.shutdown()


async def test_an_approved_reply_is_delivered_once_with_its_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    [ticket_id] = await approved_tickets(session_factory)
    helpdesk = FakeHelpdesk()

    [row] = await run_to_end(session_factory, helpdesk)

    assert row.status == TicketStatus.SENT
    assert row.sent_at is not None
    assert row.send_attempts == 1
    assert row.locked_until is None
    [request] = helpdesk.requests
    assert request.headers["idempotency-key"] == str(ticket_id)
    assert request.headers["host"] == "helpdesk.example.com"
    assert json.loads(request.content) == {"ticket_id": "T-0", "message": "Reply 0"}


async def test_a_definite_failure_is_retried_until_delivered(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await approved_tickets(session_factory)
    answers = iter([httpx.Response(503), httpx.Response(502), httpx.Response(201)])

    [row] = await run_to_end(session_factory, lambda request: next(answers))

    assert row.status == TicketStatus.SENT
    assert row.send_attempts == 3
    assert row.last_error is None


async def test_a_connection_refused_before_sending_is_retried(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await approved_tickets(session_factory)
    calls = 0

    def refuse_once(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(201)

    [row] = await run_to_end(session_factory, refuse_once)

    assert row.status == TicketStatus.SENT
    assert row.send_attempts == 2


async def test_definite_failures_stop_at_the_attempt_cap(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await approved_tickets(session_factory)
    helpdesk = FakeHelpdesk(status=503)

    [row] = await run_to_end(session_factory, helpdesk)

    assert row.status == TicketStatus.SEND_FAILED
    assert row.send_attempts == FAST.max_attempts
    assert len(helpdesk.requests) == FAST.max_attempts
    assert row.last_error == "HTTP 503"


async def test_a_client_error_fails_without_a_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await approved_tickets(session_factory)
    helpdesk = FakeHelpdesk(status=404)

    [row] = await run_to_end(session_factory, helpdesk)

    assert row.status == TicketStatus.SEND_FAILED
    assert len(helpdesk.requests) == 1


async def test_an_ambiguous_outcome_is_parked_and_never_resent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await approved_tickets(session_factory)
    helpdesk = FakeHelpdesk(hang_after_store_rate=1.0)
    sender = Sender(session_factory, helpdesk)
    try:
        [row] = await wait_until(session_factory, all_settled)
        await asyncio.sleep(FAST.lease_seconds + 0.5)
        [later] = await rows(session_factory)
    finally:
        await sender.shutdown()

    assert row.status == TicketStatus.SEND_UNKNOWN
    assert row.last_error == "ReadTimeout"
    assert later.status == TicketStatus.SEND_UNKNOWN
    assert len(helpdesk.requests) == 1


async def test_ambiguous_outcomes_are_retried_when_the_receiver_dedupes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await approved_tickets(session_factory)
    calls = 0

    def hang_once(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("hung")
        return httpx.Response(201)

    policy = replace(FAST, retry_ambiguous=True)

    [row] = await run_to_end(session_factory, hang_once, policy)

    assert row.status == TicketStatus.SENT
    assert row.send_attempts == 2


async def test_a_private_reply_url_is_refused_without_a_request(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await approved_tickets(session_factory)
    helpdesk = FakeHelpdesk()

    [row] = await run_to_end(
        session_factory, helpdesk, resolve=resolve_to("169.254.169.254")
    )

    assert row.status == TicketStatus.SEND_FAILED
    assert row.last_error == "reply_url_rejected: address"
    assert helpdesk.requests == []


async def test_an_unexpected_error_while_sending_is_treated_as_ambiguous(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await approved_tickets(session_factory)

    def explode(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("bug after the bytes left")

    [row] = await run_to_end(session_factory, explode)

    assert row.status == TicketStatus.SEND_UNKNOWN
    assert row.last_error == INTERNAL_ERROR


async def test_no_transaction_is_open_while_the_helpdesk_is_called(
    session_factory: async_sessionmaker[AsyncSession], migrated_schema: str
) -> None:
    """Only the sender's own connections count, not the test's poller."""
    await approved_tickets(session_factory, 3)
    sender_engine = create_async_engine(
        migrated_schema,
        connect_args={
            "server_settings": {
                "timezone": "UTC",
                "application_name": "sender-under-test",
            }
        },
    )
    observed: list[int] = []

    async def count_open_transactions(request: httpx.Request) -> None:
        async with session_factory() as session:
            observed.append(
                await session.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND application_name = 'sender-under-test' "
                        "AND state LIKE 'idle in transaction%'"
                    )
                )
            )

    sender = Sender(
        build_session_factory(sender_engine),
        FakeHelpdesk(on_request=count_open_transactions),
        replace(FAST, concurrency=1),
    )
    try:
        await wait_until(session_factory, all_settled)
    finally:
        await sender.shutdown()
        await sender_engine.dispose()

    assert observed == [0, 0, 0]


async def test_chaos_never_delivers_a_reply_twice(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """I6: a receiver that ignores Idempotency-Key, many 5xx, many hangs."""
    await approved_tickets(session_factory, 40)
    helpdesk = FakeHelpdesk(
        fail_5xx_rate=0.4, hang_after_store_rate=0.3, honor_idempotency_key=False
    )

    found = await run_to_end(session_factory, helpdesk)

    statuses = Counter(row.status for row in found)
    assert set(statuses) <= SETTLED
    assert max(helpdesk.deliveries.values()) == 1
    assert statuses[TicketStatus.SEND_UNKNOWN] >= 1
    assert statuses[TicketStatus.SENT] >= 1
    by_key = {str(row.id): row for row in found}
    for key in helpdesk.hung:
        assert by_key[key].status == TicketStatus.SEND_UNKNOWN
    for row in found:
        if row.status == TicketStatus.SENT:
            assert helpdesk.deliveries[str(row.id)] == 1


async def test_a_worker_killed_mid_send_leaves_the_reply_unknown(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """I6: the crashed send may have arrived, so it is parked, never resent."""
    await approved_tickets(session_factory)
    arrived = asyncio.Event()

    async def store_and_hang(request: httpx.Request) -> None:
        arrived.set()
        await asyncio.Event().wait()

    crashed = Sender(session_factory, FakeHelpdesk(on_request=store_and_hang))
    await asyncio.wait_for(arrived.wait(), timeout=5)
    await crashed.kill()

    helpdesk = FakeHelpdesk()
    [row] = await run_to_end(session_factory, helpdesk)

    assert row.status == TicketStatus.SEND_UNKNOWN
    assert row.last_error.startswith("lease_expired")
    assert helpdesk.requests == []


async def test_a_send_killed_mid_flight_is_retried_when_ambiguity_may_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await approved_tickets(session_factory)
    arrived = asyncio.Event()

    async def hang(request: httpx.Request) -> None:
        arrived.set()
        await asyncio.Event().wait()

    crashed = Sender(session_factory, FakeHelpdesk(on_request=hang))
    await asyncio.wait_for(arrived.wait(), timeout=5)
    await crashed.kill()

    helpdesk = FakeHelpdesk()
    [row] = await run_to_end(
        session_factory, helpdesk, replace(FAST, retry_ambiguous=True)
    )

    assert row.status == TicketStatus.SENT
    assert row.send_attempts == 2
    assert len(helpdesk.requests) == 1


async def test_twenty_simultaneous_approves_send_exactly_once(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """I7 end to end: double clicks and two operators produce one delivery."""
    async with session_factory() as session:
        row = TicketEvent(
            **sample_event(), status=TicketStatus.DRAFT_READY, draft_text="Reply"
        )
        session.add(row)
        await session.commit()

    responses = await asyncio.gather(
        *(
            db_client.post(f"/api/tickets/{row.id}/approve", **OPERATOR)
            for _ in range(20)
        )
    )
    helpdesk = FakeHelpdesk(honor_idempotency_key=False)
    [sent] = await run_to_end(session_factory, helpdesk)

    assert Counter(response.status_code for response in responses)[200] == 1
    assert sent.status == TicketStatus.SENT
    assert helpdesk.deliveries == {str(row.id): 1}


async def test_resend_puts_an_unknown_reply_back_in_the_queue(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    [ticket_id] = await approved_tickets(session_factory)
    async with session_factory() as session:
        await session.execute(
            update(TicketEvent).values(status=TicketStatus.SEND_UNKNOWN)
        )
        await session.commit()

    response = await db_client.post(f"/api/tickets/{ticket_id}/resend", **OPERATOR)
    helpdesk = FakeHelpdesk()
    [row] = await run_to_end(session_factory, helpdesk)

    assert response.status_code == 200
    assert row.status == TicketStatus.SENT
    assert len(helpdesk.requests) == 1


async def test_a_crashed_send_at_the_cap_is_not_requeued_even_when_ambiguity_may_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A send that keeps killing its worker stops at the attempt cap."""
    await approved_tickets(session_factory)
    async with session_factory() as session:
        await session.execute(
            update(TicketEvent).values(
                status=TicketStatus.SENDING,
                send_attempts=FAST.max_attempts,
                locked_until=func.now() - timedelta(seconds=1),
            )
        )
        await session.commit()
    helpdesk = FakeHelpdesk()
    policy = replace(FAST, retry_ambiguous=True)

    [row] = await run_to_end(session_factory, helpdesk, policy)

    assert row.status == TicketStatus.SEND_UNKNOWN
    assert row.last_error == STALE_SEND_ERROR
    assert helpdesk.requests == []


async def test_resend_after_the_cap_gets_one_more_attempt(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    [ticket_id] = await approved_tickets(session_factory)
    async with session_factory() as session:
        await session.execute(
            update(TicketEvent).values(
                status=TicketStatus.SEND_UNKNOWN, send_attempts=FAST.max_attempts
            )
        )
        await session.commit()

    response = await db_client.post(f"/api/tickets/{ticket_id}/resend", **OPERATOR)
    helpdesk = FakeHelpdesk()
    [row] = await run_to_end(session_factory, helpdesk)

    assert response.status_code == 200
    assert row.status == TicketStatus.SENT
    assert len(helpdesk.requests) == 1


async def test_an_ambiguous_last_attempt_stays_unknown_when_ambiguity_may_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await approved_tickets(session_factory)

    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("hung")

    policy = replace(FAST, retry_ambiguous=True, max_attempts=2)

    [row] = await run_to_end(session_factory, hang, policy)

    assert row.status == TicketStatus.SEND_UNKNOWN
    assert row.send_attempts == 2


async def test_a_resend_after_the_cap_that_fails_is_not_retried(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    [ticket_id] = await approved_tickets(session_factory)
    async with session_factory() as session:
        await session.execute(
            update(TicketEvent).values(
                status=TicketStatus.SEND_UNKNOWN, send_attempts=FAST.max_attempts
            )
        )
        await session.commit()

    await db_client.post(f"/api/tickets/{ticket_id}/resend", **OPERATOR)
    helpdesk = FakeHelpdesk(status=503)
    [row] = await run_to_end(session_factory, helpdesk)

    assert row.status == TicketStatus.SEND_FAILED
    assert len(helpdesk.requests) == 1
