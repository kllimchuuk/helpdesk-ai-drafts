import json
from collections.abc import Callable

import httpx2
import pytest
from anthropic import AsyncAnthropic

from llm.anthropic_client import MAX_RETRY_AFTER_S, AnthropicProvider
from llm.exceptions import (
    LLMError,
    LLMInvalidOutputError,
    LLMRateLimitedError,
    LLMRefusalError,
    LLMRejectedError,
    LLMTransientError,
)
from llm.schemas import LLMRequest

REQUEST = LLMRequest(system="Be brief.", user="How do I reset my password?")


def message(text: str, stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def draft(reply: str = "Open Settings.", cited: list[str] | None = None) -> dict:
    return message(json.dumps({"reply": reply, "cited_slugs": cited or []}))


class Recorder:
    def __init__(self, respond: Callable[[httpx2.Request], httpx2.Response]) -> None:
        self.requests: list[httpx2.Request] = []
        self._respond = respond

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self._respond(request)

    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]


def credential(request: httpx2.Request) -> str:
    return request.headers["authorization"].removeprefix("Bearer ")


def provider(recorder: Recorder) -> AnthropicProvider:
    sdk = AsyncAnthropic(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(recorder)),
    )
    return AnthropicProvider(sdk, model="claude-haiku-5-5")


def answer(status: int, body: dict, headers: dict | None = None) -> Recorder:
    return Recorder(lambda request: httpx2.Response(status, json=body, headers=headers))


async def test_a_valid_answer_becomes_a_result() -> None:
    recorder = answer(200, draft("Open Settings.", ["reset-password"]))

    result = await provider(recorder).complete(REQUEST)

    assert result.reply == "Open Settings."
    assert result.cited_slugs == ("reset-password",)
    assert result.is_static is False


async def test_the_request_asks_for_low_effort_and_a_json_schema() -> None:
    recorder = answer(200, draft())

    await provider(recorder).complete(REQUEST)

    body = recorder.bodies()[0]
    assert body["model"] == "claude-haiku-5-5"
    assert body["system"] == "Be brief."
    assert body["messages"] == [{"role": "user", "content": REQUEST.user}]
    assert body["output_config"]["effort"] == "low"
    schema = body["output_config"]["format"]["schema"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert set(schema["required"]) == {"reply", "cited_slugs"}
    assert schema["additionalProperties"] is False


async def test_no_sampling_or_thinking_budget_is_sent() -> None:
    recorder = answer(200, draft())

    await provider(recorder).complete(REQUEST)

    body = recorder.bodies()[0]
    assert not {"temperature", "top_p", "top_k"} & set(body)
    assert "budget_tokens" not in json.dumps(body)


@pytest.mark.parametrize("status", [429, 500, 529])
async def test_a_failed_request_is_never_retried_by_the_sdk(status: int) -> None:
    recorder = answer(status, {"type": "error", "error": {"type": "x", "message": "m"}})

    with pytest.raises(LLMError):
        await provider(recorder).complete(REQUEST)

    assert len(recorder.requests) == 1


async def test_a_rate_limit_carries_the_retry_after_header() -> None:
    recorder = answer(
        429,
        {"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}},
        headers={"retry-after": "7"},
    )

    with pytest.raises(LLMRateLimitedError) as caught:
        await provider(recorder).complete(REQUEST)

    assert caught.value.retry_after == 7.0


async def test_a_rate_limit_without_the_header_has_no_retry_after() -> None:
    recorder = answer(
        429, {"type": "error", "error": {"type": "rate_limit_error", "message": "x"}}
    )

    with pytest.raises(LLMRateLimitedError) as caught:
        await provider(recorder).complete(REQUEST)

    assert caught.value.retry_after is None


@pytest.mark.parametrize("status", [500, 502, 503, 529])
async def test_server_errors_are_transient(status: int) -> None:
    recorder = answer(
        status, {"type": "error", "error": {"type": "api_error", "message": "x"}}
    )

    with pytest.raises(LLMTransientError):
        await provider(recorder).complete(REQUEST)


@pytest.mark.parametrize(
    "error",
    [httpx2.ReadTimeout("slow"), httpx2.ConnectError("down")],
)
async def test_timeouts_and_connection_errors_are_transient(
    error: Exception,
) -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise error

    with pytest.raises(LLMTransientError):
        await provider(Recorder(fail)).complete(REQUEST)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_client_errors_are_rejections(status: int) -> None:
    recorder = answer(
        status,
        {"type": "error", "error": {"type": "invalid_request_error", "message": "x"}},
    )

    with pytest.raises(LLMRejectedError) as caught:
        await provider(recorder).complete(REQUEST)

    assert caught.value.payload["status"] == status


async def test_a_refusal_is_reported_as_such() -> None:
    recorder = answer(200, message("", stop_reason="refusal"))

    with pytest.raises(LLMRefusalError):
        await provider(recorder).complete(REQUEST)


@pytest.mark.parametrize(
    "body",
    [
        message("not json"),
        message(json.dumps({"reply": "x"})),
        message(json.dumps({"reply": "x", "cited_slugs": "a"})),
        message(json.dumps({"reply": "x", "cited_slugs": [], "extra": 1})),
        message(json.dumps({"reply": "", "cited_slugs": []})),
        message(json.dumps({"reply": "a\u0000b", "cited_slugs": []})),
        message(json.dumps({"reply": "x", "cited_slugs": ["a\u0000"]})),
        message('{"reply": "cut off', stop_reason="max_tokens"),
        {**message("x"), "content": []},
    ],
)
async def test_output_that_does_not_fit_the_schema_is_invalid(body: dict) -> None:
    with pytest.raises(LLMInvalidOutputError):
        await provider(answer(200, body)).complete(REQUEST)


@pytest.mark.parametrize(
    "value", ["inf", "nan", "-5", "soon", "Wed, 21 Oct 2026 07:28:00 GMT"]
)
async def test_an_unusable_retry_after_is_dropped(value: str) -> None:
    recorder = answer(
        429,
        {"type": "error", "error": {"type": "rate_limit_error", "message": "x"}},
        headers={"retry-after": value},
    )

    with pytest.raises(LLMRateLimitedError) as caught:
        await provider(recorder).complete(REQUEST)

    assert caught.value.retry_after is None


async def test_errors_do_not_carry_the_provider_response_as_their_cause() -> None:
    recorder = answer(
        500, {"type": "error", "error": {"type": "api_error", "message": "secret text"}}
    )

    with pytest.raises(LLMTransientError) as caught:
        await provider(recorder).complete(REQUEST)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


async def test_a_reply_that_breaks_the_schema_does_not_leak_into_the_error() -> None:
    body = message(json.dumps({"reply": "customer secret", "cited_slugs": "oops"}))

    with pytest.raises(LLMInvalidOutputError) as caught:
        await provider(answer(200, body)).complete(REQUEST)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, json={}),
        httpx2.Response(200, json={"content": None, "stop_reason": None}),
        httpx2.Response(200, text="<html>bad gateway</html>"),
        httpx2.Response(200, content=b""),
    ],
)
async def test_a_malformed_success_response_is_an_invalid_output(
    response: httpx2.Response,
) -> None:
    with pytest.raises(LLMError):
        await provider(Recorder(lambda request: response)).complete(REQUEST)


async def test_a_huge_retry_after_is_capped() -> None:
    recorder = answer(
        429,
        {"type": "error", "error": {"type": "rate_limit_error", "message": "x"}},
        headers={"retry-after": "1e300"},
    )

    with pytest.raises(LLMRateLimitedError) as caught:
        await provider(recorder).complete(REQUEST)

    assert caught.value.retry_after == MAX_RETRY_AFTER_S


@pytest.mark.parametrize(
    "content",
    [
        [{"type": "text"}],
        ["not an object"],
        [None],
        [{"type": "text", "text": None}],
        [{"type": "text", "text": 5}],
    ],
)
async def test_a_malformed_content_block_is_an_invalid_output(content: list) -> None:
    body = {**message("x"), "content": content}

    with pytest.raises(LLMInvalidOutputError) as caught:
        await provider(answer(200, body)).complete(REQUEST)

    assert caught.value.__context__ is None
