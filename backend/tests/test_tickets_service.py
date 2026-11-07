import uuid
from datetime import UTC, datetime

import pytest

from tests.fakes import MissingReviewRepository
from tickets.exceptions import TicketStatusConflictError
from tickets.models import TicketEvent
from tickets.service import TicketService
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
