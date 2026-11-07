from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from drafting.service import DraftingService
from llm.factory import build_llm_client
from workers.generation_loop import GenerationLoop, GenerationPolicy

# Each in-flight ticket can hold a connection while it waits for the rate
# limiter's advisory lock, next to its heartbeats and the claim query.
SPARE_CONNECTIONS = 5


def worker_pool_size(settings: Settings) -> int:
    return settings.LLM_CONCURRENCY + SPARE_CONNECTIONS


def build_generation_loop(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> GenerationLoop:
    drafting = DraftingService(
        session_factory,
        build_llm_client(settings, session_factory),
        min_score=settings.KB_MIN_SCORE,
        public_base_url=settings.PUBLIC_BASE_URL,
    )
    return GenerationLoop(
        session_factory,
        drafting,
        GenerationPolicy(concurrency=settings.LLM_CONCURRENCY),
    )
