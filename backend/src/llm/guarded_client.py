from llm.client import LLMClient
from llm.limiter import RateLimiter
from llm.route import LlmRoute
from llm.schemas import LLMRequest, LLMResult


class GuardedLLMClient(LLMClient):
    def __init__(
        self, limiter: RateLimiter, provider: LLMClient, keyless: LLMClient
    ) -> None:
        self._limiter = limiter
        self._provider = provider
        self._keyless = keyless

    async def complete(self, request: LLMRequest) -> LLMResult:
        route = await self._limiter.acquire()
        if route == LlmRoute.PROVIDER:
            return await self._provider.complete(request)
        return await self._keyless.complete(request)
