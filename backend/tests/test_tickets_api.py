import asyncio
import uuid
from collections import Counter

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers import sample_event
from tickets.models import TicketEvent
from tickets.status import TicketStatus

AUTH = ("operator", "operator")
OPERATOR_HEADERS = {
    "X-Requested-By": "operator-ui",
    "Content-Type": "application/json",
}
SOURCES = [{"slug": "reset-password", "title": "Відновлення", "url": "http://kb/x"}]


async def add_ticket(
    session_factory: async_sessionmaker[AsyncSession],
    status: TicketStatus = TicketStatus.DRAFT_READY,
    **values: object,
) -> TicketEvent:
    event = sample_event()
    row = TicketEvent(
        event_id=event["event_id"],
        ticket_id=event["ticket_id"],
        customer_email=event["customer_email"],
        message=event["message"],
        reply_url=event["reply_url"],
        status=status,
        draft_text="Draft." if status != TicketStatus.RECEIVED else None,
        draft_sources=SOURCES if status != TicketStatus.RECEIVED else None,
    )
    for name, value in values.items():
        setattr(row, name, value)
    async with session_factory() as session:
        session.add(row)
        await session.commit()
    return row


async def load(
    session_factory: async_sessionmaker[AsyncSession], ticket_id: uuid.UUID
) -> TicketEvent:
    async with session_factory() as session:
        return await session.get(TicketEvent, ticket_id)


async def act(client: AsyncClient, ticket_id: object, action: str, **kwargs):
    return await client.post(
        f"/api/tickets/{ticket_id}/{action}",
        auth=kwargs.pop("auth", AUTH),
        headers=kwargs.pop("headers", OPERATOR_HEADERS),
        **kwargs,
    )


@pytest.mark.parametrize("path", ["/api/tickets", f"/api/tickets/{uuid.uuid4()}"])
async def test_operator_reads_need_credentials(
    db_client: AsyncClient, path: str
) -> None:
    response = await db_client.get(path)

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")
    assert response.json()["code"] == "operator_auth_required"


@pytest.mark.parametrize(
    "auth", [("operator", "wrong"), ("someone", "operator"), ("", "")]
)
async def test_wrong_credentials_are_refused(
    db_client: AsyncClient, auth: tuple[str, str]
) -> None:
    response = await db_client.get("/api/tickets", auth=auth)

    assert response.status_code == 401


@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_actions_need_credentials(
    db_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    action: str,
) -> None:
    row = await add_ticket(session_factory)

    response = await db_client.post(
        f"/api/tickets/{row.id}/{action}", headers=OPERATOR_HEADERS
    )

    assert response.status_code == 401
    assert (await load(session_factory, row.id)).status == TicketStatus.DRAFT_READY


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "application/json"},
        {"X-Requested-By": "operator-ui"},
        {"X-Requested-By": "evil", "Content-Type": "application/json"},
        {"X-Requested-By": "operator-ui", "Content-Type": "text/plain"},
        {
            "X-Requested-By": "operator-ui",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    ],
)
async def test_actions_without_the_operator_ui_headers_are_refused(
    db_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    headers: dict[str, str],
) -> None:
    """A cross-site form post carries cached Basic credentials but not these."""
    row = await add_ticket(session_factory)

    response = await act(db_client, row.id, "approve", headers=headers)

    assert response.status_code == 403
    assert response.json()["code"] == "operator_header_required"
    assert (await load(session_factory, row.id)).status == TicketStatus.DRAFT_READY


async def test_the_list_is_newest_first_and_filters_by_status(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    first = await add_ticket(session_factory, TicketStatus.RECEIVED)
    second = await add_ticket(session_factory, TicketStatus.DRAFT_READY)
    third = await add_ticket(session_factory, TicketStatus.DRAFT_READY)

    everything = await db_client.get("/api/tickets", auth=AUTH)
    drafts = await db_client.get(
        "/api/tickets", params={"status": "draft_ready"}, auth=AUTH
    )

    assert everything.status_code == 200
    assert [item["id"] for item in everything.json()["items"]] == [
        str(third.id),
        str(second.id),
        str(first.id),
    ]
    assert [item["id"] for item in drafts.json()["items"]] == [
        str(third.id),
        str(second.id),
    ]


async def test_the_list_shows_a_short_preview_and_no_contact_data(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_ticket(session_factory, message="x" * 1000)

    [item] = (await db_client.get("/api/tickets", auth=AUTH)).json()["items"]

    assert len(item["message_preview"]) <= 161
    assert item["message_preview"].endswith("…")
    assert "customer_email" not in item
    assert "reply_url" not in item


async def test_the_list_is_limited(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    for _ in range(3):
        await add_ticket(session_factory)

    response = await db_client.get("/api/tickets", params={"limit": 2}, auth=AUTH)

    assert len(response.json()["items"]) == 2


@pytest.mark.parametrize(
    "params", [{"status": "nonsense"}, {"limit": 0}, {"limit": 1001}]
)
async def test_invalid_list_parameters_are_rejected(
    db_client: AsyncClient, params: dict[str, object]
) -> None:
    response = await db_client.get("/api/tickets", params=params, auth=AUTH)

    assert response.status_code == 422


async def test_a_ticket_shows_its_message_draft_and_sources(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    row = await add_ticket(
        session_factory,
        low_confidence=True,
        draft_is_static=True,
        last_error="llm_unavailable: x",
    )

    response = await db_client.get(f"/api/tickets/{row.id}", auth=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == row.message
    assert body["customer_email"] == row.customer_email
    assert body["draft_text"] == "Draft."
    assert body["draft_sources"] == SOURCES
    assert body["low_confidence"] is True
    assert body["draft_is_static"] is True
    assert body["last_error"] == "llm_unavailable: x"
    assert body["status"] == "draft_ready"


@pytest.mark.parametrize("ticket_id", [uuid.uuid4(), "not-a-uuid"])
async def test_an_unknown_ticket_is_a_404(
    db_client: AsyncClient, ticket_id: object
) -> None:
    response = await db_client.get(f"/api/tickets/{ticket_id}", auth=AUTH)

    assert response.status_code == 404
    assert response.json()["code"] == "ticket_not_found"


async def test_approve_moves_a_draft_to_approved(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    row = await add_ticket(session_factory)

    response = await act(db_client, row.id, "approve")

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    stored = await load(session_factory, row.id)
    assert stored.status == TicketStatus.APPROVED
    assert stored.reviewed_at is not None
    assert stored.next_attempt_at <= stored.reviewed_at
    assert stored.locked_until is None


async def test_reject_moves_a_draft_to_rejected(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    row = await add_ticket(session_factory)

    response = await act(db_client, row.id, "reject")

    assert response.status_code == 200
    stored = await load(session_factory, row.id)
    assert stored.status == TicketStatus.REJECTED
    assert stored.reviewed_at is not None


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.parametrize(
    "status",
    [
        TicketStatus.RECEIVED,
        TicketStatus.GENERATING,
        TicketStatus.APPROVED,
        TicketStatus.REJECTED,
        TicketStatus.SENT,
        TicketStatus.SEND_UNKNOWN,
    ],
)
async def test_only_a_ready_draft_can_be_reviewed(
    db_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    action: str,
    status: TicketStatus,
) -> None:
    row = await add_ticket(session_factory, status)

    response = await act(db_client, row.id, action)

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "ticket_status_conflict"
    assert body["payload"] == {"status": status.value}
    assert (await load(session_factory, row.id)).status == status


async def test_an_action_on_an_unknown_ticket_is_a_404(
    db_client: AsyncClient,
) -> None:
    response = await act(db_client, uuid.uuid4(), "approve")

    assert response.status_code == 404


async def test_concurrent_approves_succeed_exactly_once(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """I7: double clicks and two operators cannot approve a reply twice."""
    row = await add_ticket(session_factory)

    responses = await asyncio.gather(
        *(act(db_client, row.id, "approve") for _ in range(20))
    )

    assert Counter(response.status_code for response in responses) == {
        200: 1,
        409: 19,
    }
    assert (await load(session_factory, row.id)).status == TicketStatus.APPROVED


async def test_concurrent_approve_and_reject_leave_one_decision(
    db_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    row = await add_ticket(session_factory)

    responses = await asyncio.gather(
        *(act(db_client, row.id, action) for action in ["approve", "reject"] * 10)
    )

    winners = [r.json()["status"] for r in responses if r.status_code == 200]
    assert len(winners) == 1
    assert (await load(session_factory, row.id)).status == winners[0]


async def test_public_routes_stay_public(db_client: AsyncClient) -> None:
    assert (await db_client.get("/api/stats")).status_code == 200
    assert (await db_client.get("/health")).status_code == 200
