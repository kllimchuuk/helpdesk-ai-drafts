import asyncio
import random
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable

import httpx

from llm.client import LLMClient
from llm.schemas import LLMRequest, LLMResult
from tickets.models import TicketEvent
from tickets.status import TicketStatus

DEFAULT_RESULT = LLMResult(reply="A drafted reply.", cited_slugs=(), is_static=False)


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


class MissingReviewRepository:
    """A ticket repository whose conditional review always misses.

    It stands in for a ticket that changed between the update and the re-read,
    for example a draft the worker saved in that moment.
    """

    def __init__(self, current: TicketEvent) -> None:
        self.current = current
        self.review_calls = 0

    async def review(
        self, ticket_id: uuid.UUID, decision: TicketStatus
    ) -> TicketEvent | None:
        self.review_calls += 1
        return None

    async def get(self, ticket_id: uuid.UUID) -> TicketEvent | None:
        return self.current


class FakeHelpdesk:
    """An httpx transport handler that stores replies and injects failures.

    `hang_after_store_rate` stores the reply and then fails the read, which is
    what the sender sees when the helpdesk saved the reply but never answered.
    """

    def __init__(
        self,
        *,
        fail_5xx_rate: float = 0.0,
        hang_after_store_rate: float = 0.0,
        honor_idempotency_key: bool = True,
        status: int = 201,
        seed: int = 7,
        on_request: Callable[[httpx.Request], Awaitable[None]] | None = None,
    ) -> None:
        self.fail_5xx_rate = fail_5xx_rate
        self.hang_after_store_rate = hang_after_store_rate
        self.honor_idempotency_key = honor_idempotency_key
        self.status = status
        self.on_request = on_request
        self.requests: list[httpx.Request] = []
        self.deliveries: Counter[str] = Counter()
        self.hung: set[str] = set()
        self._random = random.Random(seed)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.on_request is not None:
            await self.on_request(request)
        key = request.headers["idempotency-key"]
        if self._random.random() < self.fail_5xx_rate:
            return httpx.Response(503)
        if self.status != 201:
            return httpx.Response(self.status)
        if not (self.honor_idempotency_key and self.deliveries[key]):
            self.deliveries[key] += 1
        if self._random.random() < self.hang_after_store_rate:
            self.hung.add(key)
            raise httpx.ReadTimeout("the helpdesk stored the reply and hung")
        return httpx.Response(201)


def resolve_to(*addresses: str) -> Callable[[str, int], Awaitable[list[str]]]:
    async def resolve(host: str, port: int) -> list[str]:
        return list(addresses)

    return resolve
