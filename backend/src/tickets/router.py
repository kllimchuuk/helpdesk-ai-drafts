from typing import Annotated

from fastapi import APIRouter, Depends, Query

from core.security import require_operator, require_operator_ui
from tickets.schemas import StatsResponse, TicketDetail, TicketListResponse
from tickets.service import TicketService, get_ticket_service
from tickets.status import TicketStatus

router = APIRouter(prefix="/api", tags=["tickets"])
operator_router = APIRouter(
    prefix="/api/tickets",
    tags=["operator"],
    dependencies=[Depends(require_operator)],
)


@router.get("/stats", response_model=StatsResponse)
async def stats(
    service: Annotated[TicketService, Depends(get_ticket_service)],
) -> StatsResponse:
    return await service.stats()


@operator_router.get("", response_model=TicketListResponse)
async def list_tickets(
    service: Annotated[TicketService, Depends(get_ticket_service)],
    status: TicketStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> TicketListResponse:
    return await service.list_tickets(status, limit)


@operator_router.get("/{ticket_id}", response_model=TicketDetail)
async def get_ticket(
    ticket_id: str,
    service: Annotated[TicketService, Depends(get_ticket_service)],
) -> TicketDetail:
    return await service.get_ticket(ticket_id)


@operator_router.post(
    "/{ticket_id}/approve",
    response_model=TicketDetail,
    dependencies=[Depends(require_operator_ui)],
)
async def approve(
    ticket_id: str,
    service: Annotated[TicketService, Depends(get_ticket_service)],
) -> TicketDetail:
    return await service.approve(ticket_id)


@operator_router.post(
    "/{ticket_id}/reject",
    response_model=TicketDetail,
    dependencies=[Depends(require_operator_ui)],
)
async def reject(
    ticket_id: str,
    service: Annotated[TicketService, Depends(get_ticket_service)],
) -> TicketDetail:
    return await service.reject(ticket_id)


@operator_router.post(
    "/{ticket_id}/mark-delivered",
    response_model=TicketDetail,
    dependencies=[Depends(require_operator_ui)],
)
async def mark_delivered(
    ticket_id: str,
    service: Annotated[TicketService, Depends(get_ticket_service)],
) -> TicketDetail:
    return await service.mark_delivered(ticket_id)


@operator_router.post(
    "/{ticket_id}/resend",
    response_model=TicketDetail,
    dependencies=[Depends(require_operator_ui)],
)
async def resend(
    ticket_id: str,
    service: Annotated[TicketService, Depends(get_ticket_service)],
) -> TicketDetail:
    return await service.resend(ticket_id)
