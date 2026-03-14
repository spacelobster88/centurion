"""End-to-end tests that run a real FastAPI app with actual endpoints.

Uses httpx.AsyncClient with ASGITransport -- no mocks for the server itself.
The Centurion engine is a real instance with a real scheduler, event bus, and registry.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from centurion.api.router import health_router, router
from centurion.config import CenturionConfig
from centurion.core.engine import Centurion


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app() -> FastAPI:
    """Create a real FastAPI app with a real Centurion engine on app.state."""
    application = FastAPI()
    application.include_router(health_router)
    application.include_router(router)

    config = CenturionConfig()
    engine = Centurion(config=config)
    application.state.centurion = engine

    return application


@pytest.fixture()
async def client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ---------------------------------------------------------------------------
# E2E Tests
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient) -> None:
    """GET /health returns 200 with status ok."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_hardware_endpoint(client: AsyncClient) -> None:
    """GET /api/centurion/hardware returns 200 with expected keys."""
    resp = await client.get("/api/centurion/hardware")
    assert resp.status_code == 200
    data = resp.json()
    assert "system" in data
    assert "allocated" in data
    assert "recommended_max_agents" in data


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_purge_endpoint(client: AsyncClient) -> None:
    """POST /api/centurion/purge returns 200 with a status key."""
    resp = await client.post("/api/centurion/purge")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_recommend_endpoint(client: AsyncClient) -> None:
    """GET /api/centurion/recommend returns 200 with a valid dict."""
    resp = await client.get("/api/centurion/recommend")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    # Should contain recommendation keys from _build_recommendation
    assert "system" in data
    assert "recommended_max_agents" in data
    assert "per_type" in data


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_health_ready_has_components(client: AsyncClient) -> None:
    """GET /health/ready returns response with components key."""
    resp = await client.get("/health/ready")
    # May be 200 or 503 depending on subsystem state, but body is always valid
    data = resp.json()
    assert "components" in data
    # Engine component should be present and ok (real engine is initialised)
    assert "engine" in data["components"]
    assert "scheduler" in data["components"]
    assert "event_bus" in data["components"]
