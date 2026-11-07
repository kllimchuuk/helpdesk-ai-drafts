import asyncio
from collections.abc import Awaitable, Callable

from llm.client import LLMClient
from llm.schemas import LLMRequest, LLMResult

DEFAULT_RESULT = LLMResult(reply="A drafted reply.", cited_slugs=[], is_static=False)


class FakeLLMClient(LLMClient):
    """Answers with the queued outcomes in order, then with the default result."""

    def __init__(
        self,
        *outcomes: LLMResult | Exception,
        default: LLMResult = DEFAULT_RESULT,
        delay: float = 0.0,
        on_call: Callable[[LLMRequest], Awaitable[None]] | None = None,
    ) -> None:
        self.requests: list[LLMRequest] = []
        self._outcomes = list(outcomes)
        self._default = default
        self._delay = delay
        self._on_call = on_call

    async def complete(self, request: LLMRequest) -> LLMResult:
        self.requests.append(request)
        if self._on_call is not None:
            await self._on_call(request)
        if self._delay:
            await asyncio.sleep(self._delay)
        outcome = self._outcomes.pop(0) if self._outcomes else self._default
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class HangingLLMClient(LLMClient):
    """Never answers, as a provider call that is in flight when a worker dies."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.calls = 0

    async def complete(self, request: LLMRequest) -> LLMResult:
        self.calls += 1
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")
