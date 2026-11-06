import contextlib
import functools
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from sqlalchemy.exc import (
    DBAPIError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
)
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.requests import HTTPConnection

from core.exceptions import DatabaseUnavailableError

logger = logging.getLogger(__name__)

UTC_SERVER_SETTINGS = {"timezone": "UTC"}

# SQLSTATE classes 08 (connection exception) and 57 (operator intervention).
UNAVAILABLE_SQLSTATE_CLASSES = ("08", "57")


def build_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"server_settings": UTC_SERVER_SETTINGS},
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def is_unavailable(error: BaseException) -> bool:
    # asyncpg reports an unreachable server as a bare OSError, not a DBAPIError,
    # and a connection lost mid-statement as a plain DBAPIError flagged as invalidated.
    if isinstance(
        error, OSError | OperationalError | InterfaceError | PoolTimeoutError
    ):
        return True
    if isinstance(error, DBAPIError):
        sqlstate = getattr(error.orig, "sqlstate", None) or ""
        return error.connection_invalidated or sqlstate.startswith(
            UNAVAILABLE_SQLSTATE_CLASSES
        )
    return False


def translate_unavailable[**P, R](
    method: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    @functools.wraps(method)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await method(*args, **kwargs)
        except (OSError, SQLAlchemyError) as error:
            if not is_unavailable(error):
                raise
            logger.warning("Database unavailable (%s)", type(error).__name__)
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
            with contextlib.suppress(OSError, SQLAlchemyError):
                await session.rollback()
            raise
