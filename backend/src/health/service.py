from typing import Annotated

from fastapi import Depends

from health.repository import HealthRepository, get_health_repository


class HealthService:
    def status(self) -> str:
        return "OK"


class ReadinessService:
    def __init__(self, repository: HealthRepository) -> None:
        self._repository = repository

    async def status(self) -> str:
        await self._repository.ping()
        return "OK"


def get_health_service() -> HealthService:
    return HealthService()


def get_readiness_service(
    repository: Annotated[HealthRepository, Depends(get_health_repository)],
) -> ReadinessService:
    return ReadinessService(repository)
