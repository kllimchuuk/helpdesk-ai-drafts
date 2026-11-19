from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from tickets.schemas import StatsResponse, TicketSummary
from tickets.status import TicketStatus


def summary(status: str) -> TicketSummary:
    now = datetime.now(UTC)
    return TicketSummary(
        id=uuid4(),
        event_id="evt",
        ticket_id="T-1",
        status=status,
        message_preview="hello",
        low_confidence=False,
        draft_is_static=False,
        created_at=now,
        updated_at=now,
    )


def test_a_ticket_status_outside_the_state_machine_is_refused() -> None:
    with pytest.raises(ValidationError):
        summary("shipped")


def test_a_known_status_is_serialized_as_its_value() -> None:
    dumped = summary("draft_ready").model_dump(mode="json")

    assert dumped["status"] == "draft_ready"


def test_stats_count_only_statuses_of_the_state_machine() -> None:
    with pytest.raises(ValidationError):
        StatsResponse(counts={"shipped": 1}, total=1)


def test_stats_are_serialized_by_status_value() -> None:
    counts = {status: 0 for status in TicketStatus}

    dumped = StatsResponse(counts=counts, total=0).model_dump(mode="json")

    assert set(dumped["counts"]) == {status.value for status in TicketStatus}
