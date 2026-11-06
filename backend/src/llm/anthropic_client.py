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
            raise classify_status(error) from None
        except anthropic.APIConnectionError as error:
            raise LLMTransientError(type(error).__name__) from None
        except anthropic.APIError as error:
            raise LLMInvalidOutputError(type(error).__name__) from None
        return to_result(response)


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
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def to_result(response: object) -> LLMResult:
    if not isinstance(response, Message):
        raise LLMInvalidOutputError("the response is not a message")
    if response.stop_reason == "refusal":
        raise LLMRefusalError()
    if response.stop_reason == "max_tokens":
        raise LLMInvalidOutputError("the answer was cut off")
    text = "".join(
        block.text for block in response.content or [] if block.type == "text"
    )
    try:
        output = DraftOutput.model_validate_json(text)
    except ValidationError:
        raise LLMInvalidOutputError("the answer does not match the schema") from None
    return LLMResult(
        reply=output.reply, cited_slugs=output.cited_slugs, is_static=False
    )
