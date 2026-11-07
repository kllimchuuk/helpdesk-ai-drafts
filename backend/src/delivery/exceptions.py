from core.exceptions import AppException


class ReplyUrlRejectedError(AppException):
    def __init__(self, reason: str) -> None:
        super().__init__(
            code="reply_url_rejected",
            message="The reply URL may not be used.",
            payload={"reason": reason},
        )


class ReplyHostUnresolvedError(AppException):
    def __init__(self) -> None:
        super().__init__(
            code="reply_host_unresolved",
            message="The reply URL host could not be resolved.",
        )
