from typing import Annotated

from fastapi import APIRouter, Depends

from tickets.schemas import StatsResponse
from tickets.service import TicketService, get_ticket_service

router = APIRouter(prefix="/api", tags=["tickets"])


@router.get("/stats", response_model=StatsResponse)
async def stats(
    service: Annotated[TicketService, Depends(get_ticket_service)],
) -> StatsResponse:
    return await service.stats()
