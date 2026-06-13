import httpx
import pytest

from app.main import create_app


@pytest.fixture
def app():
    return create_app()


async def test_healthz(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert "x-request-id" in resp.headers


async def test_public_config(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/config")  # unauthenticated
    assert resp.status_code == 200
    body = resp.json()
    # Exactly the public handles, nothing secret (no jwt_secret / service_role).
    assert set(body) == {"supabase_url", "supabase_anon_key"}
    assert "secret" not in resp.text.lower() and "service_role" not in resp.text


async def test_metrics_exposed(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/healthz")
        resp = await client.get("/metrics/")
    assert resp.status_code == 200
    assert "reglens_http_requests_total" in resp.text
