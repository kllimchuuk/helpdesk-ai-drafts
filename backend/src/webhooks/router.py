from typing import Annotated

from fastapi import APIRouter, Depends

from webhooks.schemas import WebhookPayload, WebhookResponse
from webhooks.service import WebhookService, get_webhook_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/helpdesk", response_model=WebhookResponse)
async def receive_helpdesk_event(
    payload: WebhookPayload,
    service: Annotated[WebhookService, Depends(get_webhook_service)],
) -> WebhookResponse:
    return WebhookResponse(status=await service.ingest(payload))
