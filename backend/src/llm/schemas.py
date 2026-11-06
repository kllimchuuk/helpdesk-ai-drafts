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
    cited_slugs: list[str]
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
