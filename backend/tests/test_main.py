from fastapi import FastAPI
from httpx import AsyncClient

from core.exceptions import ConflictError, NotFoundError


class ExampleConflictError(ConflictError):
    def __init__(self) -> None:
        super().__init__(
            code="example_conflict",
            message="The example conflicts.",
            payload={"id": 7},
        )


async def test_domain_error_is_rendered_with_code_message_and_payload(
    app: FastAPI, client: AsyncClient
) -> None:
    @app.get("/_test/conflict")
    async def conflict() -> None:
        raise ExampleConflictError()

    response = await client.get("/_test/conflict")

    assert response.status_code == 409
    assert response.json() == {
        "code": "example_conflict",
        "message": "The example conflicts.",
        "payload": {"id": 7},
    }


async def test_domain_error_status_follows_its_class(
    app: FastAPI, client: AsyncClient
) -> None:
    @app.get("/_test/missing")
    async def missing() -> None:
        raise NotFoundError(code="missing", message="Nothing here.")

    response = await client.get("/_test/missing")

    assert response.status_code == 404
    assert response.json()["code"] == "missing"


async def test_unexpected_error_hides_details_from_the_client(
    app: FastAPI, client: AsyncClient
) -> None:
    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    response = await client.get("/_test/boom")

    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "Internal server error",
        "payload": {},
    }
    assert "secret internal detail" not in response.text
