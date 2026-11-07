from core.exceptions import ConflictError, NotFoundError


class TicketNotFoundError(NotFoundError):
    def __init__(self) -> None:
        super().__init__(code="ticket_not_found", message="Ticket not found.")


class TicketStatusConflictError(ConflictError):
    def __init__(self, status: str) -> None:
        super().__init__(
            code="ticket_status_conflict",
            message="The ticket is not in a state that allows this action.",
            payload={"status": status},
        )
