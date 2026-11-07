import uuid
from datetime import UTC, datetime

import pytest

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


class RacingRepository:
    """The conditional update misses, then the re-read sees the given statuses."""

    def __init__(self, *, reviews: list[TicketEvent | None], reads: list[TicketEvent]):
        self.reviews = reviews
        self.reads = reads
        self.review_calls = 0

    async def review(self, ticket_id: uuid.UUID, decision: TicketStatus):
        self.review_calls += 1
        return self.reviews.pop(0)

    async def get(self, ticket_id: uuid.UUID):
        return self.reads.pop(0)


async def test_a_draft_that_became_ready_during_the_review_is_reviewed() -> None:
    """The worker saved the draft between the missed update and the re-read."""
    approved = ticket(TicketStatus.APPROVED)
    repository = RacingRepository(
        reviews=[None, approved], reads=[ticket(TicketStatus.DRAFT_READY)]
    )

    result = await TicketService(repository).approve(str(approved.id))

    assert result.status == TicketStatus.APPROVED
    assert repository.review_calls == 2


async def test_the_conflict_reports_the_status_that_blocked_the_review() -> None:
    repository = RacingRepository(
        reviews=[None, None],
        reads=[ticket(TicketStatus.DRAFT_READY), ticket(TicketStatus.REJECTED)],
    )

    with pytest.raises(TicketStatusConflictError) as caught:
        await TicketService(repository).approve(str(uuid.uuid4()))

    assert caught.value.payload == {"status": TicketStatus.REJECTED}
    assert repository.review_calls == 2
