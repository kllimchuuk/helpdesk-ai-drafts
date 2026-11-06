import logging

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
)
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import build_engine, translate_unavailable
from core.exceptions import DatabaseUnavailableError
from tests.helpers import sample_event

WEBHOOK = "/webhooks/helpdesk"


def disconnect_error() -> DBAPIError:
    return DBAPIError("SELECT 1", {}, Exception("gone"), connection_invalidated=True)


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError("refused"),
        OSError("no route"),
        OperationalError("SELECT 1", {}, Exception("down")),
        InterfaceError("SELECT 1", {}, Exception("closed")),
        disconnect_error(),
        PoolTimeoutError("QueuePool limit of size 5 overflow 10 reached"),
    ],
)
async def test_availability_problems_become_database_unavailable(
    error: Exception,
) -> None:
    @translate_unavailable
    async def failing() -> None:
        raise error

    with pytest.raises(DatabaseUnavailableError):
        await failing()


@pytest.mark.parametrize(
    "error",
    [
        IntegrityError("INSERT", {}, Exception("duplicate")),
        ProgrammingError("SELECT", {}, Exception("syntax")),
        DBAPIError("SELECT 1", {}, Exception("other")),
        ValueError("bug"),
    ],
)
async def test_other_errors_are_not_disguised_as_outages(error: Exception) -> None:
    @translate_unavailable
    async def failing() -> None:
        raise error

    with pytest.raises(type(error)):
        await failing()


async def test_connection_killed_mid_statement_is_reported_as_unavailable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    @translate_unavailable
    async def kill_own_connection() -> None:
        async with session_factory() as session:
            await session.execute(text("select pg_terminate_backend(pg_backend_pid())"))
            await session.execute(text("select 1"))

    with pytest.raises(DatabaseUnavailableError):
        await kill_own_connection()


async def test_an_outage_leaves_a_log_line_without_customer_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    @translate_unavailable
    async def failing() -> None:
        raise OperationalError(
            "INSERT ... VALUES ($1)", {"message": "secret text"}, Exception("down")
        )

    with caplog.at_level(logging.WARNING), pytest.raises(DatabaseUnavailableError):
        await failing()

    assert "Database unavailable" in caplog.text
    assert "OperationalError" in caplog.text
    assert "secret text" not in caplog.text


async def test_failed_commit_and_failed_rollback_still_answer_503(
    db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken_commit(self: AsyncSession) -> None:
        raise OperationalError("COMMIT", {}, Exception("connection lost"))

    async def broken_rollback(self: AsyncSession) -> None:
        raise OSError("connection lost")

    monkeypatch.setattr(AsyncSession, "commit", broken_commit)
    monkeypatch.setattr(AsyncSession, "rollback", broken_rollback)

    response = await db_client.post(WEBHOOK, json=sample_event())

    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"


def test_engine_keeps_statement_parameters_out_of_error_messages() -> None:
    engine = build_engine("postgresql+asyncpg://u:p@127.0.0.1:1/x")

    assert engine.sync_engine.hide_parameters is True


async def test_a_database_error_does_not_put_the_customer_message_in_the_response(
    db_app: FastAPI, db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_execute(self: AsyncSession, *args: object, **kwargs: object):
        raise IntegrityError("INSERT", {"message": "secret text"}, Exception("boom"))

    monkeypatch.setattr(AsyncSession, "execute", failing_execute)

    response = await db_client.post(WEBHOOK, json=sample_event(message="secret text"))

    assert response.status_code == 500
    assert "secret text" not in response.text
