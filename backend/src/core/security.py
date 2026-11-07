import secrets
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from config import Settings
from core.dependencies import get_settings
from core.exceptions import ForbiddenError, UnauthorizedError

OPERATOR_UI_HEADER = "x-requested-by"
OPERATOR_UI_VALUE = "operator-ui"
JSON_CONTENT_TYPE = "application/json"

basic_auth = HTTPBasic(auto_error=False, realm="operator")


class OperatorAuthRequiredError(UnauthorizedError):
    headers = {"WWW-Authenticate": 'Basic realm="operator"'}

    def __init__(self) -> None:
        super().__init__(
            code="operator_auth_required",
            message="Operator credentials are required.",
        )


class OperatorHeaderRequiredError(ForbiddenError):
    def __init__(self) -> None:
        super().__init__(
            code="operator_header_required",
            message="Operator actions must come from the operator UI.",
        )


def require_operator(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(basic_auth)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    if credentials is None or not credentials_match(credentials, settings):
        raise OperatorAuthRequiredError()
    return credentials.username


def credentials_match(credentials: HTTPBasicCredentials, settings: Settings) -> bool:
    # Both comparisons always run, in constant time, so the response time does
    # not reveal which half was wrong.
    user_ok = secrets.compare_digest(
        credentials.username.encode(), settings.OPERATOR_USER.encode()
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode(),
        settings.OPERATOR_PASSWORD.get_secret_value().encode(),
    )
    return user_ok & password_ok


def require_operator_ui(request: Request) -> None:
    # Browsers resend cached Basic credentials on cross-site form posts. A form
    # cannot set a custom header or a JSON content type without a CORS preflight,
    # which the backend never allows, so these two checks stop CSRF.
    content_type = request.headers.get("content-type", "")
    if (
        request.headers.get(OPERATOR_UI_HEADER) != OPERATOR_UI_VALUE
        or content_type.split(";")[0].strip().lower() != JSON_CONTENT_TYPE
    ):
        raise OperatorHeaderRequiredError()
