import pytest
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession


async def test_health_answers_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.text == "OK"


async def test_ready_answers_ok_when_the_database_answers(
    db_client: AsyncClient,
) -> None:
    response = await db_client.get("/health/ready")

    assert response.status_code == 200
    assert response.text == "OK"


async def test_ready_answers_503_when_the_database_is_down(
    db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_execute(self: AsyncSession, *args: object, **kwargs: object):
        raise OperationalError("SELECT 1", {}, Exception("down"))

    monkeypatch.setattr(AsyncSession, "execute", failing_execute)

    response = await db_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"


async def test_health_stays_up_when_the_database_is_down(
    db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_execute(self: AsyncSession, *args: object, **kwargs: object):
        raise OperationalError("SELECT 1", {}, Exception("down"))

    monkeypatch.setattr(AsyncSession, "execute", failing_execute)

    response = await db_client.get("/health")

    assert response.status_code == 200
