from starlette.status import HTTP_502_BAD_GATEWAY

from core.exceptions import AppException


class LLMError(AppException):
    status_code = HTTP_502_BAD_GATEWAY


class LLMRateLimitedError(LLMError):
    def __init__(self, retry_after: float | None) -> None:
        super().__init__(
            code="llm_rate_limited",
            message="The language model provider asked us to slow down.",
            payload={"retry_after": retry_after},
        )
        self.retry_after = retry_after


class LLMTransientError(LLMError):
    def __init__(self, reason: str) -> None:
        super().__init__(
            code="llm_unavailable",
            message="The language model provider is unavailable. Retry later.",
            payload={"reason": reason},
        )


class LLMRejectedError(LLMError):
    def __init__(self, status: int) -> None:
        super().__init__(
            code="llm_request_rejected",
            message="The language model provider rejected the request.",
            payload={"status": status},
        )


class LLMRefusalError(LLMError):
    def __init__(self) -> None:
        super().__init__(
            code="llm_refusal",
            message="The language model refused to answer.",
        )


class LLMInvalidOutputError(LLMError):
    def __init__(self, reason: str) -> None:
        super().__init__(
            code="llm_invalid_output",
            message="The language model answer could not be used.",
            payload={"reason": reason},
        )
