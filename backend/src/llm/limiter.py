import asyncio
import random
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from llm.repository import LlmCallRepositoryImpl
from llm.route import LlmRoute
from llm.schemas import Reservation
from llm.service import LlmCallService


class RateLimiter:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        limit: int,
        window_seconds: float,
        daily_cap: int,
        has_key: bool,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter_seconds: float = 0.05,
    ) -> None:
        self._session_factory = session_factory
        self._limit = limit
        self._window_seconds = window_seconds
        self._daily_cap = daily_cap
        self._has_key = has_key
        self._sleep = sleep
        self._jitter_seconds = jitter_seconds

    async def acquire(self) -> LlmRoute:
        while True:
            reservation = await self._reserve()
            if reservation.route is not None:
                return reservation.route
            await self._sleep(
                reservation.wait_seconds + random.uniform(0, self._jitter_seconds)
            )

    async def _reserve(self) -> Reservation:
        async with self._session_factory() as session:
            service = LlmCallService(
                LlmCallRepositoryImpl(session),
                limit=self._limit,
                window_seconds=self._window_seconds,
                daily_cap=self._daily_cap,
                has_key=self._has_key,
            )
            return await service.reserve()
