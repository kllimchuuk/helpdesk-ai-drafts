import asyncio

import httpx
import pytest

from mock_helpdesk.app import Chaos, create_app

REPLY = {"ticket_id": "T-1", "message": "Hello"}


def client(chaos: Chaos) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app(chaos))
    return httpx.AsyncClient(transport=transport, base_url="http://mock")


async def post(http: httpx.AsyncClient, key: str = "k1", **kwargs) -> httpx.Response:
    return await http.post(
        "/tickets/T-1/replies", json=REPLY, headers={"Idempotency-Key": key}, **kwargs
    )


async def report(http: httpx.AsyncClient) -> dict:
    return (await http.get("/_debug/deliveries")).json()


async def test_a_reply_is_created_and_counted() -> None:
    async with client(Chaos()) as http:
        response = await post(http)
        counts = await report(http)

    assert response.status_code == 201
    assert counts == {
        "total": 1,
        "unique": 1,
        "duplicates": 0,
        "deduplicated_requests": 0,
        "duplicate_keys": [],
    }


async def test_a_repeated_key_is_stored_once_by_default() -> None:
    async with client(Chaos()) as http:
        responses = [await post(http) for _ in range(3)]
        counts = await report(http)

    assert [response.status_code for response in responses] == [201, 201, 201]
    assert counts["total"] == 1
    assert counts["deduplicated_requests"] == 2


async def test_a_naive_receiver_stores_every_copy() -> None:
    async with client(Chaos(honor_idempotency_key=False)) as http:
        for _ in range(3):
            await post(http)
        await post(http, key="k2")
        counts = await report(http)

    assert counts["total"] == 4
    assert counts["unique"] == 2
    assert counts["duplicates"] == 2
    assert counts["duplicate_keys"] == ["k1"]


async def test_a_5xx_stores_nothing() -> None:
    async with client(Chaos(fail_5xx_rate=1.0)) as http:
        response = await post(http)
        counts = await report(http)

    assert response.status_code == 503
    assert counts["total"] == 0


async def test_a_timeout_stores_nothing_and_answers_late() -> None:
    async with client(Chaos(timeout_rate=1.0, hang_seconds=0.3)) as http:
        pending = asyncio.create_task(post(http))
        await asyncio.sleep(0.1)
        while_hanging = await report(http)
        response = await pending

    assert while_hanging["total"] == 0
    assert response.status_code == 504


async def test_hang_after_store_keeps_the_reply_before_answering() -> None:
    async with client(Chaos(hang_after_store_rate=1.0, hang_seconds=0.3)) as http:
        pending = asyncio.create_task(post(http))
        await asyncio.sleep(0.1)
        while_hanging = await report(http)
        done_early = pending.done()
        await pending

    assert while_hanging["total"] == 1
    assert done_early is False


async def test_rates_are_applied_in_proportion() -> None:
    chaos = Chaos(fail_5xx_rate=0.3, seed=1)
    async with client(chaos) as http:
        codes = [(await post(http, key=f"k{i}")).status_code for i in range(400)]

    failures = codes.count(503) / len(codes)
    assert 0.22 < failures < 0.38


async def test_reset_clears_the_counts() -> None:
    async with client(Chaos()) as http:
        await post(http)
        await http.post("/_debug/reset")
        counts = await report(http)

    assert counts["total"] == 0


@pytest.mark.parametrize(
    ("headers", "body"),
    [({}, REPLY), ({"Idempotency-Key": "k"}, {"ticket_id": "T-1"})],
)
async def test_a_request_without_key_or_message_is_rejected(
    headers: dict, body: dict
) -> None:
    async with client(Chaos()) as http:
        response = await http.post("/tickets/T-1/replies", json=body, headers=headers)
        counts = await report(http)

    assert response.status_code == 422
    assert counts["total"] == 0


@pytest.mark.parametrize(
    "rates",
    [
        {"fail_5xx_rate": -0.1},
        {"timeout_rate": 1.5},
        {"fail_5xx_rate": 0.6, "hang_after_store_rate": 0.6},
    ],
)
def test_impossible_rates_are_refused(rates: dict) -> None:
    with pytest.raises(ValueError):
        Chaos(**rates)


def test_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAIL_5XX_RATE", "0.2")
    monkeypatch.setenv("HANG_AFTER_STORE_RATE", "0.1")
    monkeypatch.setenv("HONOR_IDEMPOTENCY_KEY", "false")
    monkeypatch.setenv("SEED", "3")

    chaos = Chaos.from_environment()

    assert chaos.fail_5xx_rate == 0.2
    assert chaos.hang_after_store_rate == 0.1
    assert chaos.honor_idempotency_key is False
    assert chaos.seed == 3
