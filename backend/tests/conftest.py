from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from config import Settings
from core.database import build_engine, build_session_factory
from kb.loader import sync_articles
from main import create_app
from tests.helpers import (
    KB_DIRECTORY,
    alembic_config,
    drop_database,
    recreate_database,
)


def pytest_configure() -> None:
    app_settings = Settings()
    name = make_url(app_settings.TEST_DATABASE_URL).database

    if not name or not name.endswith("_test"):
        pytest.exit(
            f"TEST_DATABASE_URL points at database {name!r}. The suite drops that "
            f"database, so its name must end with '_test'.",
            returncode=4,
        )
    if app_settings.TEST_DATABASE_URL == app_settings.DATABASE_URL:
        pytest.exit(
            "TEST_DATABASE_URL is the same as DATABASE_URL. Running the suite "
            "would destroy the development database.",
            returncode=4,
        )


@pytest_asyncio.fixture
async def app() -> FastAPI:
    return create_app(Settings(_env_file=None))


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture(scope="session")
def database_url() -> str:
    return Settings().TEST_DATABASE_URL


@pytest.fixture(scope="session")
def migrated_schema(database_url: str) -> Iterator[str]:
    recreate_database(database_url)
    command.upgrade(alembic_config(database_url), "head")
    yield database_url
    drop_database(database_url)


@pytest.fixture
def throwaway_database(database_url: str) -> Iterator[str]:
    parsed = make_url(database_url)
    url = parsed.set(database=f"{parsed.database}_migrations").render_as_string(
        hide_password=False
    )
    recreate_database(url)
    yield url
    drop_database(url)


@pytest_asyncio.fixture
async def engine(migrated_schema: str) -> AsyncIterator[AsyncEngine]:
    engine = build_engine(migrated_schema)
    async with engine.begin() as connection:
        result = await connection.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        )
        tables = ", ".join(f'"{name}"' for name in result.scalars())
        if tables:
            await connection.execute(
                text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
            )
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return build_session_factory(engine)


@pytest_asyncio.fixture
async def db_app(migrated_schema: str, engine: AsyncEngine) -> AsyncIterator[FastAPI]:
    application = create_app(Settings(_env_file=None, DATABASE_URL=migrated_schema))
    yield application
    await application.state.db_engine.dispose()


@pytest_asyncio.fixture
async def db_client(db_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=db_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest_asyncio.fixture
async def loaded_kb(session_factory: async_sessionmaker[AsyncSession]) -> None:
    await sync_articles(session_factory, KB_DIRECTORY)
