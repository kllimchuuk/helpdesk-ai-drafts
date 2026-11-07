import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx2
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from llm.anthropic_client import AnthropicProvider
from llm.client import LLMClient
from llm.guarded_client import GuardedLLMClient
from llm.keyless import PLACEHOLDER_API_KEY, KeylessClient
from llm.limiter import RateLimiter

WINDOW_SECONDS = 60.0


def build_llm_client(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    http_client: httpx2.AsyncClient | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    uniform: Callable[[float, float], float] = random.uniform,
) -> LLMClient:
    api_key = settings.ANTHROPIC_API_KEY.get_secret_value().strip()
    limiter = RateLimiter(
        session_factory,
        limit=settings.LLM_RATE_LIMIT_PER_MINUTE,
        window_seconds=WINDOW_SECONDS,
        daily_cap=settings.LLM_DAILY_CALL_CAP,
        has_key=bool(api_key),
        sleep=sleep,
    )
    provider = AnthropicProvider(
        build_sdk(api_key or PLACEHOLDER_API_KEY, settings, http_client),
        model=settings.LLM_MODEL,
    )
    keyless_probe = AnthropicProvider(
        build_sdk(PLACEHOLDER_API_KEY, settings, http_client),
        model=settings.LLM_MODEL,
    )
    keyless = KeylessClient(
        keyless_probe,
        delay_min=settings.KEYLESS_DELAY_MIN_S,
        delay_max=settings.KEYLESS_DELAY_MAX_S,
        sleep=sleep,
        uniform=uniform,
    )
    return GuardedLLMClient(limiter, provider, keyless)


def build_sdk(
    api_key: str, settings: Settings, http_client: httpx2.AsyncClient | None
) -> AsyncAnthropic:
    return AsyncAnthropic(
        api_key=api_key,
        max_retries=0,
        timeout=settings.LLM_REQUEST_TIMEOUT_S,
        http_client=http_client,
    )
