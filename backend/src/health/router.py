from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from health.service import (
    HealthService,
    ReadinessService,
    get_health_service,
    get_readiness_service,
)

router = APIRouter(tags=["health"])


@router.get("/health", response_class=PlainTextResponse)
async def health(
    service: Annotated[HealthService, Depends(get_health_service)],
) -> str:
    return service.status()


@router.get("/health/ready", response_class=PlainTextResponse)
async def ready(
    service: Annotated[ReadinessService, Depends(get_readiness_service)],
) -> str:
    return await service.status()
