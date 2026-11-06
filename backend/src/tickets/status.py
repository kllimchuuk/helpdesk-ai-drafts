from enum import StrEnum


class TicketStatus(StrEnum):
    RECEIVED = "received"
    GENERATING = "generating"
    DRAFT_READY = "draft_ready"
    APPROVED = "approved"
    SENDING = "sending"
    SENT = "sent"
    REJECTED = "rejected"
    GENERATION_FAILED = "generation_failed"
    SEND_FAILED = "send_failed"
    SEND_UNKNOWN = "send_unknown"
