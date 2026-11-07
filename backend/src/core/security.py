import base64
import binascii
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from config import Settings
from core.dependencies import get_settings
from core.exceptions import ForbiddenError, UnauthorizedError

OPERATOR_UI_HEADER = "x-requested-by"
OPERATOR_UI_VALUE = "operator-ui"
JSON_CONTENT_TYPE = "application/json"


@dataclass(frozen=True)
class BasicCredentials:
    username: str
    password: str


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
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    credentials = parse_basic(request.headers.get("authorization", ""))
    if credentials is None or not credentials_match(credentials, settings):
        raise OperatorAuthRequiredError()
    return credentials.username


def parse_basic(header: str) -> BasicCredentials | None:
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "basic" or not token:
        return None
    try:
        decoded = base64.b64decode(token.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None
    return BasicCredentials(username=username, password=password)


def credentials_match(credentials: BasicCredentials, settings: Settings) -> bool:
    user_ok = secrets.compare_digest(
        credentials.username.encode(), settings.OPERATOR_USER.encode()
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode(),
        settings.OPERATOR_PASSWORD.get_secret_value().encode(),
    )
    return user_ok & password_ok


def require_operator_ui(request: Request) -> None:
    content_type = request.headers.get("content-type", "")
    if (
        request.headers.get(OPERATOR_UI_HEADER) != OPERATOR_UI_VALUE
        or content_type.split(";")[0].strip().lower() != JSON_CONTENT_TYPE
    ):
        raise OperatorHeaderRequiredError()
