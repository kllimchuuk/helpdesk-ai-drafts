import asyncio
import random
import time
from collections.abc import Awaitable, Callable

from llm.client import LLMClient
from llm.schemas import LLMRequest, LLMResult

PLACEHOLDER_API_KEY = "keyless-mode-placeholder"
STATIC_REPLY = (
    "Дякуємо за звернення! Це автоматична чернетка: ми вже розглядаємо ваше "
    "питання й відповімо найближчим часом. Щоб ми допомогли швидше, опишіть, "
    "будь ласка, що саме ви робили та яку помилку побачили."
)


class KeylessClient(LLMClient):
    def __init__(
        self,
        probe: LLMClient,
        *,
        delay_min: float,
        delay_max: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._probe = probe
        self._delay_min = delay_min
        self._delay_max = delay_max
        self._sleep = sleep
        self._uniform = uniform
        self._monotonic = monotonic

    async def complete(self, request: LLMRequest) -> LLMResult:
        started = self._monotonic()
        delay = self._uniform(self._delay_min, self._delay_max)
        try:
            async with asyncio.timeout(delay):
                await self._probe.complete(request)
        except Exception:
            # The request exists to behave like the keyed path; whatever comes
            # back, an authentication error or a broken body, is discarded, and a
            # hanging connection is cut off when the delay is over.
            pass
        remaining = delay - (self._monotonic() - started)
        if remaining > 0:
            await self._sleep(remaining)
        return LLMResult(reply=STATIC_REPLY, cited_slugs=[], is_static=True)
