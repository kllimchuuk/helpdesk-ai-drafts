import asyncio

from config import Settings
from core.database import build_engine, build_session_factory
from workers.dependencies import build_generation_loop, worker_pool_size


async def run_worker(settings: Settings, stop: asyncio.Event) -> None:
    engine = build_engine(settings.DATABASE_URL, pool_size=worker_pool_size(settings))
    try:
        session_factory = build_session_factory(engine)
        await build_generation_loop(settings, session_factory).run(stop)
    finally:
        await engine.dispose()
