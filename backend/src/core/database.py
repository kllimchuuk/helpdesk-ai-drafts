import functools
from collections.abc import AsyncIterator, Awaitable, Callable

from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.requests import HTTPConnection

from core.exceptions import DatabaseUnavailableError

UTC_SERVER_SETTINGS = {"timezone": "UTC"}

# asyncpg reports an unreachable server as a bare OSError, not a DBAPIError.
UNAVAILABLE_ERRORS = (OSError, OperationalError, InterfaceError)


def build_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args={"server_settings": UTC_SERVER_SETTINGS},
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def translate_unavailable[**P, R](
    method: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    @functools.wraps(method)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await method(*args, **kwargs)
        except UNAVAILABLE_ERRORS as error:
            raise DatabaseUnavailableError() from error

    return wrapper


def get_session_factory(
    conn: HTTPConnection,
) -> async_sessionmaker[AsyncSession]:
    return conn.app.state.session_factory


async def get_db(conn: HTTPConnection) -> AsyncIterator[AsyncSession]:
    async with get_session_factory(conn)() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
