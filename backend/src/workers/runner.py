import asyncio

import httpx2

from config import Settings
from core.database import build_engine, build_session_factory
from workers.dependencies import build_generation_loop, worker_pool_size


async def run_worker(
    settings: Settings,
    stop: asyncio.Event,
    *,
    http_client: httpx2.AsyncClient | None = None,
) -> None:
    engine = build_engine(settings.DATABASE_URL, pool_size=worker_pool_size(settings))
    try:
        session_factory = build_session_factory(engine)
        loop = build_generation_loop(settings, session_factory, http_client=http_client)
        await loop.run(stop)
    finally:
        await engine.dispose()
