"""Tests for health check endpoints and graceful shutdown configuration."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from centurion.api.router import health_router
from centurion.api.schemas import HealthResponse, ReadinessResponse, ComponentStatus
from centurion.config import CenturionConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(**state_attrs) -> FastAPI:
    """Create a minimal FastAPI app with health_router and optional state."""
    app = FastAPI()
    app.include_router(health_router)
    for key, value in state_attrs.items():
        setattr(app.state, key, value)
    return app


def _mock_engine(
    *,
    shutting_down: bool = False,
    legions: dict | None = None,
    active_agents: int = 0,
    recommended_max: int = 10,
    subscribers: int = 0,
    history_size: int = 0,
    has_db: bool = False,
) -> MagicMock:
    """Build a MagicMock that satisfies the readiness probe checks."""
    engine = MagicMock()
    engine._shutting_down = shutting_down
    engine.legions = legions if legions is not None else {}

    # Scheduler
    engine.scheduler.probe_system.return_value = None
    engine.scheduler.active_agents = active_agents
    engine.scheduler.recommended_max_agents.return_value = recommended_max

    # EventBus
    engine.event_bus._subscribers = [None] * subscribers
    engine.event_bus._history = [None] * history_size

    # Database
    if has_db:
        engine.db = MagicMock()
    else:
        engine.db = None

    return engine


# ---------------------------------------------------------------------------
# 1. Liveness — GET /health
# ---------------------------------------------------------------------------

class TestHealthLiveness:
    def test_health_returns_ok(self):
        """GET /health returns 200 with {"status": "ok"}."""
        app = _make_app()
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"

    def test_health_response_model(self):
        """HealthResponse defaults to status='ok'."""
        h = HealthResponse()
        assert h.status == "ok"


# ---------------------------------------------------------------------------
# 2. Readiness — GET /health/ready (no engine)
# ---------------------------------------------------------------------------

class TestHealthReadinessNoEngine:
    def test_health_ready_without_engine(self):
        """GET /health/ready returns 503 when no engine is set on app.state."""
        app = _make_app()  # no centurion attribute
        client = TestClient(app)
        response = client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        # Engine component should report an error
        assert body["components"]["engine"]["status"] == "error"
        assert "not initialized" in body["components"]["engine"]["error"].lower()

    def test_ready_without_engine_reports_all_errors(self):
        """When no engine is present, all components report errors."""
        app = _make_app()
        client = TestClient(app)
        body = client.get("/health/ready").json()
        for name in ("engine", "scheduler", "event_bus", "database"):
            assert body["components"][name]["status"] == "error", (
                f"Component {name!r} should be 'error' when engine is absent"
            )


# ---------------------------------------------------------------------------
# 3. Readiness — GET /health/ready (engine present)
# ---------------------------------------------------------------------------

class TestHealthReadinessWithEngine:
    def test_health_ready_with_engine(self):
        """GET /health/ready returns 200 when a fully mocked engine is set."""
        engine = _mock_engine(has_db=True)
        app = _make_app(centurion=engine)
        client = TestClient(app)
        response = client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["components"]["engine"]["status"] == "ok"
        assert body["components"]["scheduler"]["status"] == "ok"
        assert body["components"]["event_bus"]["status"] == "ok"
        assert body["components"]["database"]["status"] == "ok"

    def test_ready_engine_shutting_down(self):
        """Readiness returns 503 when the engine is shutting down."""
        engine = _mock_engine(shutting_down=True, has_db=True)
        app = _make_app(centurion=engine)
        client = TestClient(app)
        response = client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["components"]["engine"]["status"] == "error"
        assert body["components"]["engine"]["shutting_down"] is True

    def test_ready_reports_active_agents(self):
        """Readiness includes scheduler active_agents and recommended_max."""
        engine = _mock_engine(active_agents=5, recommended_max=20, has_db=True)
        app = _make_app(centurion=engine)
        client = TestClient(app)
        body = client.get("/health/ready").json()
        assert body["components"]["scheduler"]["active_agents"] == 5
        assert body["components"]["scheduler"]["recommended_max"] == 20

    def test_ready_reports_event_bus_stats(self):
        """Readiness includes event_bus subscriber and history counts."""
        engine = _mock_engine(subscribers=3, history_size=42, has_db=True)
        app = _make_app(centurion=engine)
        client = TestClient(app)
        body = client.get("/health/ready").json()
        assert body["components"]["event_bus"]["subscribers"] == 3
        assert body["components"]["event_bus"]["history_size"] == 42

    def test_ready_no_database(self):
        """Readiness returns 503 when engine has no database attached."""
        engine = _mock_engine(has_db=False)
        app = _make_app(centurion=engine)
        client = TestClient(app)
        response = client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["components"]["database"]["status"] == "error"

    def test_ready_scheduler_probe_failure(self):
        """Readiness reports scheduler error when probe_system() raises."""
        engine = _mock_engine(has_db=True)
        engine.scheduler.probe_system.side_effect = RuntimeError("CPU on fire")
        app = _make_app(centurion=engine)
        client = TestClient(app)
        response = client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["components"]["scheduler"]["status"] == "error"
        assert "CPU on fire" in body["components"]["scheduler"]["error"]


# ---------------------------------------------------------------------------
# 4. Config — shutdown_timeout and event_buffer_size
# ---------------------------------------------------------------------------

class TestConfigEnvVars:
    def test_shutdown_timeout_default(self):
        """CenturionConfig.shutdown_timeout defaults to 60."""
        config = CenturionConfig()
        assert config.shutdown_timeout == 60.0

    def test_shutdown_timeout_configurable(self, monkeypatch):
        """CENTURION_SHUTDOWN_TIMEOUT env var overrides the default."""
        monkeypatch.setenv("CENTURION_SHUTDOWN_TIMEOUT", "120")
        config = CenturionConfig()
        assert config.shutdown_timeout == 120.0

    def test_event_buffer_size_default(self):
        """CenturionConfig.event_buffer_size defaults to 1000."""
        config = CenturionConfig()
        assert config.event_buffer_size == 1000

    def test_event_buffer_size_configurable(self, monkeypatch):
        """CENTURION_EVENT_BUFFER_SIZE env var overrides the default."""
        monkeypatch.setenv("CENTURION_EVENT_BUFFER_SIZE", "5000")
        config = CenturionConfig()
        assert config.event_buffer_size == 5000


# ---------------------------------------------------------------------------
# 5. Engine — _shutting_down flag
# ---------------------------------------------------------------------------

class TestEngineShuttingDownFlag:
    def test_engine_has_shutting_down_flag(self):
        """Centurion.__init__ sets _shutting_down = False."""
        from centurion.core.engine import Centurion

        engine = Centurion()
        assert hasattr(engine, "_shutting_down")
        assert engine._shutting_down is False

    def test_engine_shutdown_timeout_from_config(self):
        """Engine uses config.shutdown_timeout during shutdown."""
        config = CenturionConfig()
        config_with_timeout = CenturionConfig()
        # Verify the engine stores the config and the timeout is accessible
        from centurion.core.engine import Centurion

        engine = Centurion(config=config_with_timeout)
        assert engine.config.shutdown_timeout == config_with_timeout.shutdown_timeout


# ---------------------------------------------------------------------------
# 6. Schema models
# ---------------------------------------------------------------------------

class TestSchemaModels:
    def test_component_status_ok(self):
        """ComponentStatus with status='ok' has no error by default."""
        cs = ComponentStatus(status="ok")
        assert cs.status == "ok"
        assert cs.error is None

    def test_component_status_error(self):
        """ComponentStatus with status='error' can carry an error message."""
        cs = ComponentStatus(status="error", error="Something broke")
        assert cs.status == "error"
        assert cs.error == "Something broke"

    def test_readiness_response_model(self):
        """ReadinessResponse can be constructed with component dict."""
        r = ReadinessResponse(
            status="ready",
            components={"engine": ComponentStatus(status="ok")},
        )
        assert r.status == "ready"
        assert r.components["engine"].status == "ok"
