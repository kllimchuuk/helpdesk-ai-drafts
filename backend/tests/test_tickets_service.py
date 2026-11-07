import uuid
from datetime import UTC, datetime

import pytest

from tests.fakes import MissingReviewRepository
from tickets.exceptions import TicketStatusConflictError
from tickets.models import TicketEvent
from tickets.service import TicketService, claimed_send, claimed_ticket
from tickets.status import TicketStatus


def ticket(status: TicketStatus) -> TicketEvent:
    now = datetime.now(UTC)
    return TicketEvent(
        id=uuid.uuid4(),
        event_id="evt_1",
        ticket_id="T-1",
        customer_email="u@example.com",
        message="Hi",
        reply_url="https://h/r",
        status=status,
        low_confidence=False,
        draft_is_static=False,
        gen_attempts=1,
        send_attempts=0,
        created_at=now,
        updated_at=now,
    )


async def test_an_approve_that_raced_a_new_draft_is_refused() -> None:
    """The approve was sent before the draft existed, so nobody has read it."""
    repository = MissingReviewRepository(ticket(TicketStatus.DRAFT_READY))

    with pytest.raises(TicketStatusConflictError) as caught:
        await TicketService(repository).approve(str(repository.current.id))

    assert caught.value.payload == {"status": TicketStatus.DRAFT_READY}
    assert repository.review_calls == 1


async def test_the_conflict_reports_the_current_status() -> None:
    repository = MissingReviewRepository(ticket(TicketStatus.REJECTED))

    with pytest.raises(TicketStatusConflictError) as caught:
        await TicketService(repository).reject(str(repository.current.id))

    assert caught.value.payload == {"status": TicketStatus.REJECTED}


class ListRecorder:
    """Records which listing the service asks the repository for."""

    def __init__(self) -> None:
        self.calls: list[tuple[TicketStatus | None, int]] = []

    async def list_recent(self, limit: int) -> list[TicketEvent]:
        self.calls.append((None, limit))
        return []

    async def list_by_status(
        self, status: TicketStatus, limit: int
    ) -> list[TicketEvent]:
        self.calls.append((status, limit))
        return []


async def test_listing_without_a_status_asks_for_the_most_recent_tickets() -> None:
    repository = ListRecorder()

    await TicketService(repository).list_tickets(None, 50)

    assert repository.calls == [(None, 50)]


async def test_listing_with_a_status_asks_for_that_status_only() -> None:
    repository = ListRecorder()

    await TicketService(repository).list_tickets(TicketStatus.DRAFT_READY, 50)

    assert repository.calls == [(TicketStatus.DRAFT_READY, 50)]


def test_a_claimed_generation_row_becomes_a_ticket_with_its_attempt() -> None:
    row = ticket(TicketStatus.GENERATING)
    row.gen_attempts = 3

    claimed = claimed_ticket(row)

    assert (claimed.id, claimed.event_id, claimed.ticket_id) == (
        row.id,
        "evt_1",
        "T-1",
    )
    assert (claimed.message, claimed.attempt) == ("Hi", 3)


def test_a_claimed_send_row_carries_the_reply_and_the_send_attempt() -> None:
    row = ticket(TicketStatus.SENDING)
    row.draft_text = "Reply"
    row.send_attempts = 2

    claimed = claimed_send(row)

    assert (claimed.reply_url, claimed.reply, claimed.attempt) == (
        "https://h/r",
        "Reply",
        2,
    )
