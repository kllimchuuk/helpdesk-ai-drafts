import asyncio

import httpx2
import pytest
from anthropic import AsyncAnthropic

from llm.anthropic_client import AnthropicProvider
from llm.client import LLMClient
from llm.keyless import PLACEHOLDER_API_KEY, STATIC_REPLY, KeylessClient
from llm.schemas import LLMRequest, LLMResult
from tests.test_llm_client import REQUEST, Recorder, answer, credential, draft


class FakeTime:
    def __init__(self, probe_takes: float = 0.0) -> None:
        self.now = 100.0
        self.probe_takes = probe_takes
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def after_probe(self) -> None:
        self.now += self.probe_takes


def keyless(
    recorder: Recorder, clock: FakeTime, *, delay: float = 12.0
) -> KeylessClient:
    sdk = AsyncAnthropic(
        api_key=PLACEHOLDER_API_KEY,
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(recorder)),
    )
    return KeylessClient(
        AnthropicProvider(sdk, model="claude-haiku-5-5"),
        delay_min=5,
        delay_max=30,
        sleep=clock.sleep,
        uniform=lambda low, high: delay,
        monotonic=clock.monotonic,
    )


UNAUTHORIZED = {
    "type": "error",
    "error": {"type": "authentication_error", "message": "x"},
}


def unauthorized() -> Recorder:
    return answer(401, UNAUTHORIZED)


async def test_a_real_request_is_sent_with_the_placeholder_credential() -> None:
    recorder = unauthorized()

    await keyless(recorder, FakeTime()).complete(REQUEST)

    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert request.url.path == "/v1/messages"
    assert credential(request) == PLACEHOLDER_API_KEY


@pytest.mark.parametrize(
    "recorder",
    [
        unauthorized(),
        answer(200, draft("A real answer that must be ignored.")),
        answer(500, {"type": "error", "error": {"type": "api_error", "message": "x"}}),
    ],
)
async def test_the_response_is_ignored_whatever_it_is(recorder: Recorder) -> None:
    result = await keyless(recorder, FakeTime()).complete(REQUEST)

    assert result.reply == STATIC_REPLY
    assert result.cited_slugs == ()
    assert result.is_static is True


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, json={}),
        httpx2.Response(200, json={"content": None, "stop_reason": None}),
        httpx2.Response(200, text="<html>bad gateway</html>"),
        httpx2.Response(200, content=b""),
    ],
)
async def test_a_malformed_success_response_is_ignored_too(
    response: httpx2.Response,
) -> None:
    result = await keyless(Recorder(lambda request: response), FakeTime()).complete(
        REQUEST
    )

    assert result.is_static is True


class HangingProbe(LLMClient):
    async def complete(self, request: LLMRequest) -> LLMResult:
        await asyncio.sleep(30)
        raise AssertionError("the probe should have been cut off")


async def test_a_hanging_request_is_cut_off_at_the_delay() -> None:
    clock = FakeTime()
    client = KeylessClient(
        HangingProbe(),
        delay_min=0.05,
        delay_max=0.05,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    result = await asyncio.wait_for(client.complete(REQUEST), timeout=5)

    assert result.is_static is True


async def test_a_network_failure_does_not_stop_the_static_reply() -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down")

    result = await keyless(Recorder(fail), FakeTime()).complete(REQUEST)

    assert result.is_static is True


async def test_the_total_time_equals_the_random_delay() -> None:
    clock = FakeTime()

    await keyless(unauthorized(), clock, delay=12.0).complete(REQUEST)

    assert clock.slept == [12.0]


async def test_time_spent_on_the_request_counts_towards_the_delay() -> None:
    clock = FakeTime(probe_takes=4.0)
    recorder = Recorder(
        lambda request: (
            clock.after_probe(),
            httpx2.Response(
                401,
                json={
                    "type": "error",
                    "error": {"type": "authentication_error", "message": "x"},
                },
            ),
        )[1]
    )

    await keyless(recorder, clock, delay=12.0).complete(REQUEST)

    assert clock.slept == [8.0]


async def test_a_slow_request_adds_no_extra_wait() -> None:
    clock = FakeTime(probe_takes=20.0)
    recorder = Recorder(
        lambda request: (
            clock.after_probe(),
            httpx2.Response(
                401,
                json={
                    "type": "error",
                    "error": {"type": "authentication_error", "message": "x"},
                },
            ),
        )[1]
    )

    await keyless(recorder, clock, delay=12.0).complete(REQUEST)

    assert clock.slept == []


async def test_the_delay_is_drawn_between_the_configured_bounds() -> None:
    drawn: list[tuple[float, float]] = []
    sdk = AsyncAnthropic(
        api_key=PLACEHOLDER_API_KEY,
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(unauthorized())),
    )
    clock = FakeTime()

    def uniform(low: float, high: float) -> float:
        drawn.append((low, high))
        return low

    client = KeylessClient(
        AnthropicProvider(sdk, model="claude-haiku-5-5"),
        delay_min=5,
        delay_max=30,
        sleep=clock.sleep,
        uniform=uniform,
        monotonic=clock.monotonic,
    )

    await client.complete(LLMRequest(system="s", user="u"))

    assert drawn == [(5, 30)]


async def test_cancelling_the_caller_still_propagates() -> None:
    client = KeylessClient(
        HangingProbe(), delay_min=20, delay_max=20, sleep=FakeTime().sleep
    )
    task = asyncio.ensure_future(client.complete(REQUEST))
    await asyncio.sleep(0.05)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
