"""Health endpoint tests (M0 exit criterion: health endpoint returns)."""

import httpx
import pytest

from app.main import create_app


@pytest.fixture
def client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_returns_ok(client: httpx.AsyncClient) -> None:
    async with client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "TenderScore"


async def test_health_reports_environment(client: httpx.AsyncClient) -> None:
    async with client:
        response = await client.get("/health")
    assert response.json()["environment"] in {"development", "test", "production"}
