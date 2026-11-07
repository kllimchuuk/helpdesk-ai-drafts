import asyncio
import os
import random
from collections import Counter
from dataclasses import dataclass

from fastapi import FastAPI, Header, Response
from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Chaos:
    """Failure rates are drawn in this order from one random number per request."""

    fail_5xx_rate: float = 0.0
    timeout_rate: float = 0.0
    hang_after_store_rate: float = 0.0
    honor_idempotency_key: bool = True
    hang_seconds: float = 60.0
    seed: int | None = None

    def __post_init__(self) -> None:
        rates = (self.fail_5xx_rate, self.timeout_rate, self.hang_after_store_rate)
        if any(not 0.0 <= rate <= 1.0 for rate in rates) or sum(rates) > 1.0:
            raise ValueError("chaos rates must be within 0-1 and add up to at most 1")

    @classmethod
    def from_environment(cls) -> "Chaos":
        seed = os.environ.get("SEED")
        return cls(
            fail_5xx_rate=float(os.environ.get("FAIL_5XX_RATE", "0")),
            timeout_rate=float(os.environ.get("TIMEOUT_RATE", "0")),
            hang_after_store_rate=float(os.environ.get("HANG_AFTER_STORE_RATE", "0")),
            honor_idempotency_key=os.environ.get("HONOR_IDEMPOTENCY_KEY", "true")
            .strip()
            .lower()
            not in ("false", "0", "no"),
            hang_seconds=float(os.environ.get("HANG_SECONDS", "60")),
            seed=int(seed) if seed else None,
        )


class Reply(BaseModel):
    ticket_id: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1)


class Deliveries(BaseModel):
    total: int
    unique: int
    duplicates: int
    deduplicated_requests: int
    duplicate_keys: list[str]


class Store:
    def __init__(self) -> None:
        self.stored: Counter[str] = Counter()
        self.deduplicated = 0

    def save(self, key: str, honor_key: bool) -> None:
        if honor_key and self.stored[key]:
            self.deduplicated += 1
            return
        self.stored[key] += 1

    def report(self) -> Deliveries:
        total = sum(self.stored.values())
        duplicate_keys = sorted(key for key, count in self.stored.items() if count > 1)
        return Deliveries(
            total=total,
            unique=len(self.stored),
            duplicates=total - len(self.stored),
            deduplicated_requests=self.deduplicated,
            duplicate_keys=duplicate_keys,
        )


def create_app(chaos: Chaos | None = None) -> FastAPI:
    chaos = chaos or Chaos.from_environment()
    store = Store()
    draw = random.Random(chaos.seed).random
    app = FastAPI(title="Mock helpdesk")

    @app.post("/tickets/{ticket_id}/replies", status_code=201)
    async def receive_reply(
        ticket_id: str,
        reply: Reply,
        response: Response,
        idempotency_key: str = Header(min_length=1, max_length=255),
    ) -> dict[str, str]:
        roll = draw()
        if roll < chaos.fail_5xx_rate:
            response.status_code = 503
            return {"status": "unavailable"}
        roll -= chaos.fail_5xx_rate
        if roll < chaos.timeout_rate:
            await asyncio.sleep(chaos.hang_seconds)
            response.status_code = 504
            return {"status": "timed out"}
        roll -= chaos.timeout_rate
        store.save(idempotency_key, chaos.honor_idempotency_key)
        if roll < chaos.hang_after_store_rate:
            # Stored, then silent: the sender cannot tell whether it arrived.
            await asyncio.sleep(chaos.hang_seconds)
        return {"status": "created"}

    @app.get("/_debug/deliveries", response_model=Deliveries)
    async def deliveries() -> Deliveries:
        return store.report()

    @app.post("/_debug/reset", status_code=204)
    async def reset() -> None:
        store.stored.clear()
        store.deduplicated = 0

    @app.get("/health")
    async def health() -> Response:
        return Response("OK", media_type="text/plain")

    return app


app = create_app()
