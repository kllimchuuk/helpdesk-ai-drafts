import asyncio

import httpx
import httpx2

from config import Settings
from core.database import build_engine, build_session_factory
from delivery.helpdesk_client import build_http_client
from delivery.ssrf import Resolver, system_resolve
from workers.dependencies import (
    build_generation_loop,
    build_send_loop,
    worker_pool_size,
)


async def run_worker(
    settings: Settings,
    stop: asyncio.Event,
    *,
    http_client: httpx2.AsyncClient | None = None,
    helpdesk_transport: httpx.AsyncBaseTransport | None = None,
    resolve: Resolver = system_resolve,
) -> None:
    engine = build_engine(settings.DATABASE_URL, pool_size=worker_pool_size(settings))
    try:
        session_factory = build_session_factory(engine)
        async with build_http_client(helpdesk_transport) as helpdesk_http:
            generation = build_generation_loop(
                settings, session_factory, http_client=http_client
            )
            sending = build_send_loop(
                settings, session_factory, helpdesk_http, resolve=resolve
            )
            await asyncio.gather(generation.run(stop), sending.run(stop))
    finally:
        await engine.dispose()
