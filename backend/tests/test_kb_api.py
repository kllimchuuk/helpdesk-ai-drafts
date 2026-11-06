import pytest
from httpx import AsyncClient


async def test_an_article_is_returned_without_credentials(
    loaded_kb: None, db_client: AsyncClient
) -> None:
    response = await db_client.get("/api/kb/export-report-pdf")

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "export-report-pdf"
    assert body["title"] == "Експорт звіту в PDF"
    assert "PDF" in body["body"]
    assert set(body) == {"slug", "title", "body"}


@pytest.mark.parametrize(
    "slug",
    ["no-such-article", "EXPORT-REPORT-PDF", "%27%20OR%201%3D1"],
)
async def test_an_unknown_article_is_a_404(
    loaded_kb: None, db_client: AsyncClient, slug: str
) -> None:
    response = await db_client.get(f"/api/kb/{slug}")

    assert response.status_code == 404
    assert response.json()["code"] == "kb_article_not_found"


async def test_a_path_that_tries_to_leave_the_route_is_a_404(
    loaded_kb: None, db_client: AsyncClient
) -> None:
    response = await db_client.get("/api/kb/..%2Fetc%2Fpasswd")

    assert response.status_code == 404
