from httpx import AsyncClient


async def test_health_answers_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.text == "OK"


async def test_health_needs_no_credentials_or_database(client: AsyncClient) -> None:
    response = await client.get("/health", headers={})

    assert response.status_code == 200
