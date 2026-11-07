import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers import sample_event
from tickets.models import TicketEvent
from tickets.repository import TicketRepositoryImpl
from tickets.schemas import ClaimedSend, ClaimedTicket
from tickets.service import claimed_send, claimed_ticket
from tickets.status import TicketStatus
from workers.send_loop import STALE_SEND_ERROR

LEASE = 120.0


async def insert_events(
    session_factory: async_sessionmaker[AsyncSession], count: int
) -> None:
    async with session_factory() as session:
        repository = TicketRepositoryImpl(session)
        for _ in range(count):
            await repository.insert_if_new(**sample_event())


async def claim(
    session_factory: async_sessionmaker[AsyncSession],
    limit: int = 10,
    lease: float = LEASE,
) -> list[ClaimedTicket]:
    async with session_factory() as session:
        rows = await TicketRepositoryImpl(session).claim_for_generation(limit, lease)
    return [claimed_ticket(row) for row in rows]


async def load(
    session_factory: async_sessionmaker[AsyncSession], ticket_id: uuid.UUID
) -> TicketEvent:
    async with session_factory() as session:
        return await session.get(TicketEvent, ticket_id)


async def expire_leases(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await session.execute(
            update(TicketEvent).values(locked_until=func.now() - timedelta(seconds=1))
        )
        await session.commit()


async def test_a_claim_leases_the_row_and_counts_the_attempt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 1)

    [ticket] = await claim(session_factory)

    row = await load(session_factory, ticket.id)
    assert ticket.attempt == 1
    assert row.status == TicketStatus.GENERATING
    assert row.gen_attempts == 1
    assert timedelta(seconds=110) < row.locked_until - row.updated_at
    assert row.locked_until - row.updated_at <= timedelta(seconds=LEASE)


async def test_a_leased_row_is_not_claimed_again(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 1)
    await claim(session_factory)

    assert await claim(session_factory) == []


async def test_a_row_whose_lease_expired_is_claimed_with_the_next_attempt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 1)
    [first] = await claim(session_factory)
    await expire_leases(session_factory)

    [second] = await claim(session_factory)

    assert second.id == first.id
    assert second.attempt == 2


async def test_a_row_scheduled_for_later_is_not_claimed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 1)
    [ticket] = await claim(session_factory)
    async with session_factory() as session:
        await TicketRepositoryImpl(session).retry_generation(
            ticket, delay_seconds=60, error="llm_unavailable"
        )

    assert await claim(session_factory) == []
    row = await load(session_factory, ticket.id)
    assert row.status == TicketStatus.RECEIVED
    assert row.locked_until is None
    assert row.last_error == "llm_unavailable"


async def test_rows_in_other_statuses_are_never_claimed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, len(TicketStatus))
    async with session_factory() as session:
        ids = list(await session.scalars(select(TicketEvent.id)))
        for ticket_id, status in zip(ids, TicketStatus, strict=True):
            await session.execute(
                update(TicketEvent)
                .where(TicketEvent.id == ticket_id)
                .values(status=status)
            )
        await session.commit()

    claimed = await claim(session_factory, limit=50)

    assert len(claimed) == 2


async def test_concurrent_claims_never_hand_out_a_row_twice(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 60)

    batches = await asyncio.gather(
        *(claim(session_factory, limit=4) for _ in range(20))
    )

    ids = [ticket.id for batch in batches for ticket in batch]
    assert len(ids) == 60
    assert len(set(ids)) == 60


async def test_a_stale_worker_cannot_overwrite_the_new_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 1)
    [stale] = await claim(session_factory)
    await expire_leases(session_factory)
    [current] = await claim(session_factory)

    async with session_factory() as session:
        repository = TicketRepositoryImpl(session)
        stale_saved = await repository.save_draft(
            stale, text="stale", sources=[], low_confidence=False, is_static=False
        )
        stale_extended = await repository.extend_generation_lease(stale, LEASE)
        stale_failed = await repository.fail_generation(stale, error="x")
        current_saved = await repository.save_draft(
            current,
            text="fresh",
            sources=[{"slug": "a", "title": "A", "url": "u"}],
            low_confidence=True,
            is_static=True,
        )

    assert (stale_saved, stale_extended, stale_failed) == (False, False, False)
    assert current_saved is True
    row = await load(session_factory, current.id)
    assert row.status == TicketStatus.DRAFT_READY
    assert row.draft_text == "fresh"
    assert row.draft_sources == [{"slug": "a", "title": "A", "url": "u"}]
    assert row.low_confidence is True
    assert row.draft_is_static is True
    assert row.locked_until is None


async def test_a_finished_row_cannot_be_written_again(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 1)
    [ticket] = await claim(session_factory)

    async with session_factory() as session:
        repository = TicketRepositoryImpl(session)
        first = await repository.fail_generation(ticket, error="llm_refusal")
        second = await repository.retry_generation(
            ticket, delay_seconds=0, error="late"
        )

    assert (first, second) == (True, False)
    row = await load(session_factory, ticket.id)
    assert row.status == TicketStatus.GENERATION_FAILED
    assert row.last_error == "llm_refusal"


async def test_extending_the_lease_moves_it_forward(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 1)
    [ticket] = await claim(session_factory, lease=1)

    async with session_factory() as session:
        extended = await TicketRepositoryImpl(session).extend_generation_lease(
            ticket, LEASE
        )

    row = await load(session_factory, ticket.id)
    assert extended is True
    assert row.locked_until - row.updated_at > timedelta(seconds=110)


async def approve_all(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await session.execute(
            update(TicketEvent).values(status=TicketStatus.APPROVED, draft_text="Hi")
        )
        await session.commit()


async def claim_sends(
    session_factory: async_sessionmaker[AsyncSession], limit: int = 10
) -> list[ClaimedSend]:
    async with session_factory() as session:
        rows = await TicketRepositoryImpl(session).claim_for_sending(limit, LEASE)
    return [claimed_send(row) for row in rows]


async def test_a_send_claim_leases_an_approved_row_and_counts_the_attempt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 1)
    await approve_all(session_factory)

    [send] = await claim_sends(session_factory)

    row = await load(session_factory, send.id)
    assert send.attempt == 1
    assert send.reply == "Hi"
    assert send.reply_url == row.reply_url
    assert row.status == TicketStatus.SENDING
    assert await claim_sends(session_factory) == []


async def test_concurrent_send_claims_never_hand_out_a_row_twice(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 40)
    await approve_all(session_factory)

    batches = await asyncio.gather(
        *(claim_sends(session_factory, limit=3) for _ in range(20))
    )

    ids = [send.id for batch in batches for send in batch]
    assert sorted(ids) == sorted(set(ids))
    assert len(ids) == 40


async def test_an_expired_send_becomes_unknown_and_is_not_claimed_again(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 1)
    await approve_all(session_factory)
    [send] = await claim_sends(session_factory)
    await expire_leases(session_factory)

    async with session_factory() as session:
        expired = await TicketRepositoryImpl(session).park_stale_sends(
            error=STALE_SEND_ERROR
        )

    row = await load(session_factory, send.id)
    assert expired == 1
    assert row.status == TicketStatus.SEND_UNKNOWN
    assert row.last_error == STALE_SEND_ERROR
    assert await claim_sends(session_factory) == []


async def test_an_expired_send_is_requeued_when_ambiguity_may_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 1)
    await approve_all(session_factory)
    await claim_sends(session_factory)
    await expire_leases(session_factory)

    async with session_factory() as session:
        await TicketRepositoryImpl(session).requeue_stale_sends(
            max_attempts=8, error=STALE_SEND_ERROR
        )

    [again] = await claim_sends(session_factory)
    assert again.attempt == 2


async def test_a_live_send_is_not_expired(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 1)
    await approve_all(session_factory)
    [send] = await claim_sends(session_factory)

    async with session_factory() as session:
        repository = TicketRepositoryImpl(session)
        expired = await repository.park_stale_sends(error=STALE_SEND_ERROR)
        requeued = await repository.requeue_stale_sends(
            max_attempts=8, error=STALE_SEND_ERROR
        )

    assert expired == 0
    assert requeued == 0
    assert (await load(session_factory, send.id)).status == TicketStatus.SENDING


async def test_a_stale_sender_cannot_overwrite_the_new_attempt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 1)
    await approve_all(session_factory)
    [stale] = await claim_sends(session_factory)
    await expire_leases(session_factory)
    async with session_factory() as session:
        await TicketRepositoryImpl(session).requeue_stale_sends(
            max_attempts=8, error=STALE_SEND_ERROR
        )
    [current] = await claim_sends(session_factory)

    async with session_factory() as session:
        repository = TicketRepositoryImpl(session)
        stale_results = [
            await repository.mark_sent(stale),
            await repository.retry_send(stale, delay_seconds=0, error="x"),
            await repository.fail_send(stale, error="x"),
            await repository.park_unknown(stale, error="x"),
        ]
        current_sent = await repository.mark_sent(current)

    assert stale_results == [False, False, False, False]
    assert current_sent is True
    row = await load(session_factory, current.id)
    assert row.status == TicketStatus.SENT
    assert row.sent_at is not None


async def test_an_expired_send_at_the_cap_is_not_requeued_and_is_then_parked(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await insert_events(session_factory, 1)
    await approve_all(session_factory)
    [send] = await claim_sends(session_factory)
    await expire_leases(session_factory)

    async with session_factory() as session:
        repository = TicketRepositoryImpl(session)
        requeued = await repository.requeue_stale_sends(
            max_attempts=1, error=STALE_SEND_ERROR
        )
        await repository.park_stale_sends(error=STALE_SEND_ERROR)

    assert requeued == 0
    assert (await load(session_factory, send.id)).status == TicketStatus.SEND_UNKNOWN
    assert await claim_sends(session_factory) == []
