from typing import Annotated, Literal

from fastapi import Depends

from tickets.repository import TicketRepository, get_ticket_repository
from webhooks.schemas import WebhookPayload


class WebhookService:
    def __init__(self, tickets: TicketRepository) -> None:
        self._tickets = tickets

    async def ingest(self, payload: WebhookPayload) -> Literal["accepted", "duplicate"]:
        inserted = await self._tickets.insert_if_new(
            event_id=payload.event_id,
            ticket_id=payload.ticket_id,
            customer_email=payload.customer_email,
            message=payload.message,
            reply_url=str(payload.reply_url),
        )
        return "accepted" if inserted else "duplicate"


def get_webhook_service(
    tickets: Annotated[TicketRepository, Depends(get_ticket_repository)],
) -> WebhookService:
    return WebhookService(tickets)
