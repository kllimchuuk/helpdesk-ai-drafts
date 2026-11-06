from abc import ABC, abstractmethod

from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import translate_unavailable
from llm.models import LlmCall
from llm.route import LlmRoute

RESERVATION_LOCK_ID = 7_364_892_002

WINDOW = (
    "called_at > clock_timestamp() - make_interval(secs => CAST(:window AS float8))"
)
TODAY_UTC = "date_trunc('day', clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"


class LlmCallRepository(ABC):
    @abstractmethod
    async def lock_reservations(self) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def count_in_window(self, window_seconds: float) -> int:
        raise NotImplementedError()

    @abstractmethod
    async def seconds_until_slot(self, window_seconds: float, skip: int) -> float:
        """Seconds until the call `skip` places after the oldest leaves the window."""
        raise NotImplementedError()

    @abstractmethod
    async def count_provider_calls_today(self) -> int:
        raise NotImplementedError()

    @abstractmethod
    async def record(self, route: LlmRoute) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def commit(self) -> None:
        raise NotImplementedError()


class LlmCallRepositoryImpl(LlmCallRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @translate_unavailable
    async def lock_reservations(self) -> None:
        # Held until commit: concurrent reservations take turns, so the window
        # count and the insert that follows it cannot interleave across workers.
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": RESERVATION_LOCK_ID}
        )

    @translate_unavailable
    async def count_in_window(self, window_seconds: float) -> int:
        return await self._session.scalar(
            text(f"SELECT count(*) FROM llm_calls WHERE {WINDOW}"),
            {"window": window_seconds},
        )

    @translate_unavailable
    async def seconds_until_slot(self, window_seconds: float, skip: int) -> float:
        seconds = await self._session.scalar(
            text(
                "SELECT extract(epoch FROM called_at "
                "+ make_interval(secs => CAST(:window AS float8)) - clock_timestamp()) "
                f"FROM llm_calls WHERE {WINDOW} "
                "ORDER BY called_at OFFSET :skip LIMIT 1"
            ),
            {"window": window_seconds, "skip": skip},
        )
        return float(seconds or 0.0)

    @translate_unavailable
    async def count_provider_calls_today(self) -> int:
        return await self._session.scalar(
            text(
                "SELECT count(*) FROM llm_calls "
                f"WHERE kind = 'provider' AND called_at >= {TODAY_UTC}"
            )
        )

    @translate_unavailable
    async def record(self, route: LlmRoute) -> None:
        await self._session.execute(insert(LlmCall).values(kind=route.value))

    @translate_unavailable
    async def commit(self) -> None:
        await self._session.commit()
