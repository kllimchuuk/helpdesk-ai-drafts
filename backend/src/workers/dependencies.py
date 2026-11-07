import httpx
import httpx2
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from delivery.helpdesk_client import HelpdeskClient
from delivery.ssrf import Resolver, system_resolve
from drafting.service import DraftingService
from llm.factory import build_llm_client
from workers.generation_loop import GenerationLoop, GenerationPolicy
from workers.send_loop import SendLoop, SendPolicy

SPARE_CONNECTIONS = 5


def worker_pool_size(settings: Settings) -> int:
    return settings.LLM_CONCURRENCY + settings.SEND_CONCURRENCY + SPARE_CONNECTIONS


def build_generation_loop(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    http_client: httpx2.AsyncClient | None = None,
) -> GenerationLoop:
    drafting = DraftingService(
        session_factory,
        build_llm_client(settings, session_factory, http_client=http_client),
        min_score=settings.KB_MIN_SCORE,
        public_base_url=settings.PUBLIC_BASE_URL,
    )
    return GenerationLoop(
        session_factory,
        drafting,
        GenerationPolicy(concurrency=settings.LLM_CONCURRENCY),
    )


def build_send_loop(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    helpdesk_http: httpx.AsyncClient,
    *,
    resolve: Resolver = system_resolve,
) -> SendLoop:
    helpdesk = HelpdeskClient(
        helpdesk_http,
        allowed_hosts=settings.reply_url_allowed_hosts,
        resolve=resolve,
    )
    return SendLoop(
        session_factory,
        helpdesk,
        SendPolicy(
            concurrency=settings.SEND_CONCURRENCY,
            retry_ambiguous=settings.SEND_RETRY_AMBIGUOUS,
        ),
    )
