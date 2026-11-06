from httpx import AsyncClient


async def test_health_answers_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.text == "OK"
