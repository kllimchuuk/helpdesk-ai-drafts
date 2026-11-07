from dataclasses import dataclass
from enum import StrEnum


class SendResult(StrEnum):
    DELIVERED = "delivered"
    RETRY = "retry"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SendOutcome:
    result: SendResult
    detail: str


@dataclass(frozen=True)
class PinnedTarget:
    host: str
    address: str
