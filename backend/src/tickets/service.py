from typing import Annotated

from fastapi import Depends

from tickets.repository import TicketRepository, get_ticket_repository
from tickets.schemas import StatsResponse
from tickets.status import TicketStatus


class TicketService:
    def __init__(self, repository: TicketRepository) -> None:
        self._repository = repository

    async def stats(self) -> StatsResponse:
        found = await self._repository.count_by_status()
        counts = {status.value: found.get(status.value, 0) for status in TicketStatus}
        return StatsResponse(counts=counts, total=sum(counts.values()))


def get_ticket_service(
    repository: Annotated[TicketRepository, Depends(get_ticket_repository)],
) -> TicketService:
    return TicketService(repository)
