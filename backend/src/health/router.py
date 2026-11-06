from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from health.service import HealthService, get_health_service

router = APIRouter(tags=["health"])


@router.get("/health", response_class=PlainTextResponse)
async def health(
    service: Annotated[HealthService, Depends(get_health_service)],
) -> str:
    return service.status()
