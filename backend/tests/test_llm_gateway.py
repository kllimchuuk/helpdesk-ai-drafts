import json

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from llm.exceptions import LLMTransientError
from llm.factory import build_llm_client
from llm.keyless import PLACEHOLDER_API_KEY, STATIC_REPLY
from tests.test_llm_client import REQUEST, Recorder, credential, draft

REAL_KEY = "sk-real-key"


def provider_api() -> Recorder:
    def respond(request: httpx2.Request) -> httpx2.Response:
        if credential(request) == PLACEHOLDER_API_KEY:
            return httpx2.Response(
                401,
                json={
                    "type": "error",
                    "error": {"type": "authentication_error", "message": "x"},
                },
            )
        return httpx2.Response(200, json=draft("A drafted reply."))

    return Recorder(respond)


def gateway(
    session_factory: async_sessionmaker[AsyncSession],
    recorder: Recorder,
    slept: list[float],
    **settings: object,
):
    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    configured = Settings(_env_file=None, **settings)
    return build_llm_client(
        configured,
        session_factory,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(recorder)),
        sleep=sleep,
        uniform=lambda low, high: low,
    )


def real_calls(recorder: Recorder) -> int:
    return sum(credential(request) == REAL_KEY for request in recorder.requests)


async def stored_kinds(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[str]:
    async with session_factory() as session:
        rows = await session.execute(text("SELECT kind FROM llm_calls ORDER BY id"))
        return list(rows.scalars())


async def test_with_a_key_the_provider_answers_and_the_call_is_logged(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    recorder = provider_api()
    client = gateway(
        session_factory, recorder, [], ANTHROPIC_API_KEY=SecretStr(REAL_KEY)
    )

    result = await client.complete(REQUEST)

    assert result.reply == "A drafted reply."
    assert result.is_static is False
    assert real_calls(recorder) == 1
    assert await stored_kinds(session_factory) == ["provider"]


async def test_without_a_key_the_static_reply_follows_a_real_request(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    recorder = provider_api()
    slept: list[float] = []
    client = gateway(session_factory, recorder, slept, ANTHROPIC_API_KEY=SecretStr(""))

    result = await client.complete(REQUEST)

    assert result.reply == STATIC_REPLY
    assert result.is_static is True
    assert [credential(r) for r in recorder.requests] == [PLACEHOLDER_API_KEY]
    assert len(slept) == 1
    assert 4 < slept[0] <= 5
    assert await stored_kinds(session_factory) == ["keyless"]


async def test_the_built_client_never_retries_a_failed_request(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    recorder = Recorder(
        lambda request: httpx2.Response(
            500, json={"type": "error", "error": {"type": "api_error", "message": "x"}}
        )
    )
    client = gateway(
        session_factory, recorder, [], ANTHROPIC_API_KEY=SecretStr(REAL_KEY)
    )

    with pytest.raises(LLMTransientError):
        await client.complete(REQUEST)

    assert len(recorder.requests) == 1


async def test_a_blank_key_counts_as_no_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client = gateway(
        session_factory, provider_api(), [], ANTHROPIC_API_KEY=SecretStr("  ")
    )

    result = await client.complete(REQUEST)

    assert result.is_static is True


async def test_after_the_daily_cap_the_provider_sees_only_the_capped_calls(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    recorder = provider_api()
    client = gateway(
        session_factory,
        recorder,
        [],
        ANTHROPIC_API_KEY=SecretStr(REAL_KEY),
        LLM_DAILY_CALL_CAP=3,
    )

    results = [await client.complete(REQUEST) for _ in range(5)]

    assert [result.is_static for result in results] == [False] * 3 + [True] * 2
    assert real_calls(recorder) == 3
    assert len(recorder.requests) == 5
    assert await stored_kinds(session_factory) == ["provider"] * 3 + ["keyless"] * 2


async def test_the_rate_limit_applies_to_the_keyless_request_too(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO llm_calls (kind) SELECT 'provider' "
                "FROM generate_series(1, 2)"
            )
        )
        await session.commit()
    waits: list[float] = []

    async def free_window(seconds: float) -> None:
        waits.append(seconds)
        async with session_factory() as session:
            await session.execute(text("DELETE FROM llm_calls"))
            await session.commit()

    client = build_llm_client(
        Settings(
            _env_file=None,
            ANTHROPIC_API_KEY=SecretStr(""),
            LLM_RATE_LIMIT_PER_MINUTE=2,
        ),
        session_factory,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(provider_api())),
        sleep=free_window,
        uniform=lambda low, high: low,
    )

    result = await client.complete(REQUEST)

    assert len(waits) == 2
    assert 50 < waits[0] <= 61
    assert 4 < waits[1] <= 5
    assert result.is_static is True


def test_the_key_never_appears_in_the_settings_repr() -> None:
    settings = Settings(_env_file=None, ANTHROPIC_API_KEY=SecretStr(REAL_KEY))

    assert REAL_KEY not in repr(settings)
    assert REAL_KEY not in json.dumps(settings.model_dump(mode="json"))
