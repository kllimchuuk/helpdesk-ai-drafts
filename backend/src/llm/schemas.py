from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, field_validator

from llm.route import LlmRoute


@dataclass(frozen=True)
class Reservation:
    route: LlmRoute | None
    wait_seconds: float = 0.0


@dataclass(frozen=True)
class LLMRequest:
    system: str
    user: str


@dataclass(frozen=True)
class LLMResult:
    reply: str
    cited_slugs: tuple[str, ...]
    is_static: bool


class DraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: str
    cited_slugs: list[str]

    @field_validator("reply")
    @classmethod
    def reply_is_not_blank(cls, reply: str) -> str:
        if not reply.strip():
            raise ValueError("the reply is blank")
        return reply

    @field_validator("reply", "cited_slugs")
    @classmethod
    def has_no_nul(cls, value: str | list[str]) -> str | list[str]:
        texts = [value] if isinstance(value, str) else value
        if any("\x00" in text for text in texts):
            raise ValueError("NUL characters are not allowed")
        return value
