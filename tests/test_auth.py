"""Tests for X-Centurion-Token authentication middleware."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from centurion.api.auth import TokenAuthMiddleware
from centurion.api.router import health_router, router

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> FastAPI:
    """Build a minimal app with auth middleware and health + API routers."""
    app = FastAPI()
    app.add_middleware(TokenAuthMiddleware)
    app.include_router(health_router)
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# 1. Health endpoints are always public
# ---------------------------------------------------------------------------

class TestHealthBypassesAuth:
    def test_health_without_token(self, monkeypatch):
        """GET /health returns 200 even when auth is enabled and no token is sent."""
        monkeypatch.setenv("CENTURION_AUTH_TOKEN", "secret-token-123")
        app = _make_app()
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_ready_without_token(self, monkeypatch):
        """GET /health/ready is accessible without a token (returns 503 because
        no engine is attached, but the point is it is NOT 401)."""
        monkeypatch.setenv("CENTURION_AUTH_TOKEN", "secret-token-123")
        app = _make_app()
        client = TestClient(app)
        response = client.get("/health/ready")
        # 503 is expected (no engine), but NOT 401
        assert response.status_code != 401


# ---------------------------------------------------------------------------
# 2. Protected endpoints require valid token
# ---------------------------------------------------------------------------

class TestProtectedEndpoints:
    def test_missing_token_returns_401(self, monkeypatch):
        """A protected endpoint returns 401 when no X-Centurion-Token header is sent."""
        monkeypatch.setenv("CENTURION_AUTH_TOKEN", "secret-token-123")
        app = _make_app()
        client = TestClient(app)
        response = client.get("/api/centurion/status")
        assert response.status_code == 401
        assert "Missing" in response.json()["detail"]

    def test_invalid_token_returns_401(self, monkeypatch):
        """A protected endpoint returns 401 when the wrong token is sent."""
        monkeypatch.setenv("CENTURION_AUTH_TOKEN", "secret-token-123")
        app = _make_app()
        client = TestClient(app)
        response = client.get(
            "/api/centurion/status",
            headers={"X-Centurion-Token": "wrong-token"},
        )
        assert response.status_code == 401
        assert "Invalid" in response.json()["detail"]

    def test_valid_token_passes(self, monkeypatch):
        """A protected endpoint succeeds when the correct token is provided.

        Note: this will fail with a 500 because no engine is attached to
        app.state, but the important assertion is that it does NOT return 401.
        """
        monkeypatch.setenv("CENTURION_AUTH_TOKEN", "secret-token-123")
        app = _make_app()
        # Attach a minimal engine to avoid 500
        from unittest.mock import MagicMock

        engine = MagicMock()
        engine.legions = {}
        engine.fleet_status.return_value = {
            "total_legions": 0,
            "total_centuries": 0,
            "total_legionaries": 0,
            "hardware": {},
        }
        app.state.centurion = engine

        client = TestClient(app)
        response = client.get(
            "/api/centurion/status",
            headers={"X-Centurion-Token": "secret-token-123"},
        )
        assert response.status_code == 200

    def test_multiple_protected_endpoints(self, monkeypatch):
        """Several different protected paths all return 401 without a token."""
        monkeypatch.setenv("CENTURION_AUTH_TOKEN", "secret-token-123")
        app = _make_app()
        client = TestClient(app)

        paths = [
            "/api/centurion/status",
            "/api/centurion/legions",
            "/api/centurion/hardware",
            "/api/centurion/agent-types",
        ]
        for path in paths:
            response = client.get(path)
            assert response.status_code == 401, f"{path} should require auth"


# ---------------------------------------------------------------------------
# 3. Auth disabled when CENTURION_AUTH_TOKEN is not set
# ---------------------------------------------------------------------------

class TestAuthDisabledWithoutEnvVar:
    def test_no_env_var_allows_access(self, monkeypatch):
        """When CENTURION_AUTH_TOKEN is unset, all endpoints are accessible."""
        monkeypatch.delenv("CENTURION_AUTH_TOKEN", raising=False)
        app = _make_app()

        from unittest.mock import MagicMock

        engine = MagicMock()
        engine.legions = {}
        engine.fleet_status.return_value = {
            "total_legions": 0,
            "total_centuries": 0,
            "total_legionaries": 0,
            "hardware": {},
        }
        app.state.centurion = engine

        client = TestClient(app)
        response = client.get("/api/centurion/status")
        assert response.status_code == 200

    def test_empty_env_var_allows_access(self, monkeypatch):
        """An empty CENTURION_AUTH_TOKEN is treated as 'not set'."""
        monkeypatch.setenv("CENTURION_AUTH_TOKEN", "")
        app = _make_app()

        from unittest.mock import MagicMock

        engine = MagicMock()
        engine.legions = {}
        engine.fleet_status.return_value = {
            "total_legions": 0,
            "total_centuries": 0,
            "total_legionaries": 0,
            "hardware": {},
        }
        app.state.centurion = engine

        client = TestClient(app)
        response = client.get("/api/centurion/status")
        assert response.status_code == 200
