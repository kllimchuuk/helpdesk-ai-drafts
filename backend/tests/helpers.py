import asyncio
import uuid
from pathlib import Path
from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import build_engine
from core.registry import metadata
from tickets.models import TicketEvent

BACKEND_DIR = Path(__file__).resolve().parents[1]
KB_DIRECTORY = BACKEND_DIR / "content" / "knowledge_base"


def sample_event(**overrides: str) -> dict[str, str]:
    event = {
        "event_id": f"evt_{uuid.uuid4().hex[:8]}",
        "ticket_id": "T-1042",
        "customer_email": "user@example.com",
        "message": "Не можу експортувати звіт у PDF",
        "reply_url": "https://helpdesk.example.com/tickets/T-1042/replies",
    }
    event.update(overrides)
    return event


async def count_events(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(TicketEvent))


def alembic_config(url: str) -> Config:
    config = Config(BACKEND_DIR / "alembic.ini")
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.attributes["sqlalchemy.url"] = url
    return config


async def _on_maintenance_database(url: str, statement: str) -> None:
    admin_url = make_url(url).set(database="postgres")
    engine = build_engine(
        admin_url.render_as_string(hide_password=False)
    ).execution_options(isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


def drop_database(url: str) -> None:
    name = make_url(url).database
    asyncio.run(
        _on_maintenance_database(url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    )


def recreate_database(url: str) -> None:
    drop_database(url)
    name = make_url(url).database
    asyncio.run(_on_maintenance_database(url, f'CREATE DATABASE "{name}"'))


async def _read(url: str, reader: Any) -> Any:
    engine = build_engine(url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(reader)
    finally:
        await engine.dispose()


def table_names(url: str) -> list[str]:
    return asyncio.run(_read(url, lambda c: inspect(c).get_table_names()))


def _diff(connection: Connection) -> list:
    context = MigrationContext.configure(
        connection, opts={"compare_type": True, "compare_server_default": True}
    )
    return compare_metadata(context, metadata)


def schema_diff(url: str) -> list:
    return asyncio.run(_read(url, _diff))
