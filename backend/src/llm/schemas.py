from dataclasses import dataclass

from llm.route import LlmRoute


@dataclass(frozen=True)
class Reservation:
    route: LlmRoute | None
    wait_seconds: float = 0.0
