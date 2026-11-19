from llm.repository import LlmCallRepository
from llm.route import LlmRoute
from llm.schemas import Reservation

MIN_WAIT_SECONDS = 0.01


class LlmCallService:
    def __init__(
        self,
        repository: LlmCallRepository,
        *,
        limit: int,
        window_seconds: float,
        daily_cap: int,
        has_key: bool,
    ) -> None:
        self._repository = repository
        self._limit = limit
        self._window_seconds = window_seconds
        self._daily_cap = daily_cap
        self._has_key = has_key

    async def reserve(self) -> Reservation:
        await self._repository.lock_reservations()
        recent = await self._repository.count_in_window(self._window_seconds)
        if recent >= self._limit:
            return await self._wait_for_slot(recent)
        route = await self._choose_route()
        await self._repository.record(route)
        await self._repository.commit()
        return Reservation(route=route)

    async def _wait_for_slot(self, recent: int) -> Reservation:
        seconds = await self._repository.seconds_until_slot(
            self._window_seconds, skip=recent - self._limit
        )
        await self._repository.commit()
        return Reservation(
            route=None, wait_seconds=max(seconds or 0.0, MIN_WAIT_SECONDS)
        )

    async def _choose_route(self) -> LlmRoute:
        if not self._has_key:
            return LlmRoute.KEYLESS
        used_today = await self._repository.count_provider_calls_today()
        if used_today >= self._daily_cap:
            return LlmRoute.KEYLESS
        return LlmRoute.PROVIDER
