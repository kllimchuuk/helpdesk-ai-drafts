import httpx

from delivery.schemas import SendOutcome, SendResult

NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def classify_status(status: int) -> SendOutcome:
    detail = f"HTTP {status}"
    if status == 201:
        return SendOutcome(SendResult.DELIVERED, detail)
    if status in (408, 429) or status >= 500:
        return SendOutcome(SendResult.RETRY, detail)
    if 300 <= status < 500:
        return SendOutcome(SendResult.FAILED, detail)
    return SendOutcome(SendResult.UNKNOWN, detail)


def classify_error(error: httpx.TransportError) -> SendOutcome:
    detail = type(error).__name__
    if isinstance(error, NOT_SENT):
        return SendOutcome(SendResult.RETRY, detail)
    return SendOutcome(SendResult.UNKNOWN, detail)
