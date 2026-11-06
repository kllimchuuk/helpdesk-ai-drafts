import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers import sample_event
from tickets.models import TicketEvent
from tickets.status import TicketStatus


async def test_stats_list_every_status_even_when_empty(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert set(body["counts"]) == {status.value for status in TicketStatus}
    assert set(body["counts"].values()) == {0}


async def test_stats_count_tickets_by_status(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    statuses = [
        TicketStatus.RECEIVED,
        TicketStatus.RECEIVED,
        TicketStatus.DRAFT_READY,
        TicketStatus.SENT,
    ]
    async with session_factory() as session:
        for status in statuses:
            event = sample_event()
            session.add(
                TicketEvent(
                    event_id=event["event_id"],
                    ticket_id=event["ticket_id"],
                    customer_email=event["customer_email"],
                    message=event["message"],
                    reply_url=event["reply_url"],
                    status=status,
                )
            )
        await session.commit()

    body = (await db_client.get("/api/stats")).json()

    assert body["total"] == 4
    assert body["counts"]["received"] == 2
    assert body["counts"]["draft_ready"] == 1
    assert body["counts"]["sent"] == 1
    assert body["counts"]["approved"] == 0


def test_statuses_match_the_spec() -> None:
    assert {status.value for status in TicketStatus} == {
        "received",
        "generating",
        "draft_ready",
        "approved",
        "sending",
        "sent",
        "rejected",
        "generation_failed",
        "send_failed",
        "send_unknown",
    }


@pytest.mark.parametrize("status", ["unknown", "", "SENT"])
async def test_database_rejects_an_unknown_status(
    session_factory: async_sessionmaker[AsyncSession], status: str
) -> None:
    from sqlalchemy.exc import IntegrityError

    event = sample_event()
    async with session_factory() as session:
        session.add(
            TicketEvent(
                event_id=event["event_id"],
                ticket_id=event["ticket_id"],
                customer_email=event["customer_email"],
                message=event["message"],
                reply_url=event["reply_url"],
                status=status,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.parametrize("status", list(TicketStatus))
async def test_database_accepts_every_status_in_the_enum(
    session_factory: async_sessionmaker[AsyncSession], status: TicketStatus
) -> None:
    event = sample_event()
    async with session_factory() as session:
        session.add(
            TicketEvent(
                event_id=event["event_id"],
                ticket_id=event["ticket_id"],
                customer_email=event["customer_email"],
                message=event["message"],
                reply_url=event["reply_url"],
                status=status,
            )
        )
        await session.commit()
