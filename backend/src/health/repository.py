from abc import ABC, abstractmethod
from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, translate_unavailable


class HealthRepository(ABC):
    @abstractmethod
    async def ping(self) -> None:
        raise NotImplementedError()


class HealthRepositoryImpl(HealthRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @translate_unavailable
    async def ping(self) -> None:
        await self._session.execute(text("SELECT 1"))


def get_health_repository(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> HealthRepository:
    return HealthRepositoryImpl(session)
