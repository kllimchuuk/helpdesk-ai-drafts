import math

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import Message
from pydantic import ValidationError

from llm.client import LLMClient
from llm.exceptions import (
    LLMError,
    LLMInvalidOutputError,
    LLMRateLimitedError,
    LLMRefusalError,
    LLMRejectedError,
    LLMTransientError,
)
from llm.schemas import DraftOutput, LLMRequest, LLMResult

MAX_TOKENS = 4096
MAX_RETRY_AFTER_S = 3600.0
OUTPUT_CONFIG = {
    "effort": "low",
    "format": {"type": "json_schema", "schema": DraftOutput.model_json_schema()},
}


class AnthropicProvider(LLMClient):
    def __init__(self, sdk: AsyncAnthropic, *, model: str) -> None:
        self._sdk = sdk
        self._model = model

    async def complete(self, request: LLMRequest) -> LLMResult:
        try:
            response = await self._sdk.messages.create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=request.system,
                messages=[{"role": "user", "content": request.user}],
                output_config=OUTPUT_CONFIG,
            )
        except anthropic.APIStatusError as error:
            failure = classify_status(error)
        except anthropic.APIConnectionError as error:
            failure = LLMTransientError(type(error).__name__)
        except anthropic.APIError as error:
            failure = LLMInvalidOutputError(type(error).__name__)
        else:
            return to_result(response)
        # Raised outside the except blocks so no exception context is attached:
        # the provider's response body and the model's reply can hold customer text.
        raise failure


def classify_status(error: anthropic.APIStatusError) -> LLMError:
    status = error.status_code
    if status == 429:
        return LLMRateLimitedError(parse_retry_after(error.response.headers))
    if status >= 500 or status == 408:
        return LLMTransientError(f"HTTP {status}")
    return LLMRejectedError(status)


def parse_retry_after(headers: object) -> float | None:
    try:
        seconds = float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_S)


def to_result(response: object) -> LLMResult:
    if not isinstance(response, Message):
        raise LLMInvalidOutputError("the response is not a message")
    if response.stop_reason == "refusal":
        raise LLMRefusalError()
    if response.stop_reason == "max_tokens":
        raise LLMInvalidOutputError("the answer was cut off")
    output = parse_output(response)
    if output is None:
        raise LLMInvalidOutputError("the answer does not match the schema")
    return LLMResult(
        reply=output.reply, cited_slugs=tuple(output.cited_slugs), is_static=False
    )


def parse_output(response: Message) -> DraftOutput | None:
    try:
        text = "".join(
            block.text for block in response.content or [] if block.type == "text"
        )
        return DraftOutput.model_validate_json(text)
    except (AttributeError, TypeError, ValidationError):
        return None
