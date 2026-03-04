"""Tests for FastAPI router endpoints using httpx AsyncClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from centurion.api.router import health_router, request_logging_middleware, router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(**state_attrs) -> FastAPI:
    """Create a minimal FastAPI app with both routers and optional state."""
    app = FastAPI()
    app.middleware("http")(request_logging_middleware)
    app.include_router(health_router)
    app.include_router(router)
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
    db: MagicMock | None = None,
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
    if db is not None:
        engine.db = db
    elif has_db:
        engine.db = MagicMock()
    else:
        engine.db = None

    return engine


# ---------------------------------------------------------------------------
# 1. Health endpoint returns 200
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    async def test_health_returns_200(self):
        """GET /health returns 200 with status ok."""
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# 2. Readiness endpoint checks subsystems
# ---------------------------------------------------------------------------

class TestReadinessEndpoint:
    async def test_readiness_all_ok(self):
        """GET /health/ready returns 200 when all subsystems are healthy."""
        engine = _mock_engine(has_db=True)
        app = _make_app(centurion=engine)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        for comp in body["components"].values():
            assert comp["status"] == "ok"

    async def test_readiness_no_engine_returns_503(self):
        """GET /health/ready returns 503 when no engine is attached."""
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["components"]["engine"]["status"] == "error"


# ---------------------------------------------------------------------------
# 3. DB errors in get_task return 503 not bare 500 (S8 fix)
# ---------------------------------------------------------------------------

class TestGetTaskDBError:
    async def test_get_task_db_error_returns_503(self):
        """GET /api/centurion/tasks/{id} returns 503 on database error, not 500."""
        db = AsyncMock()
        db.get_task = AsyncMock(side_effect=RuntimeError("connection lost"))
        engine = _mock_engine(db=db)
        app = _make_app(centurion=engine)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/centurion/tasks/task-abc123")
        assert response.status_code == 503
        assert "temporarily unavailable" in response.json()["detail"].lower()

    async def test_get_task_not_found_returns_404(self):
        """GET /api/centurion/tasks/{id} returns 404 when task does not exist."""
        db = AsyncMock()
        db.get_task = AsyncMock(return_value=None)
        engine = _mock_engine(db=db)
        app = _make_app(centurion=engine)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/centurion/tasks/task-nonexist")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 4. DB errors in cancel_task return 503 not bare 500 (S8 fix)
# ---------------------------------------------------------------------------

class TestCancelTaskDBError:
    async def test_cancel_task_db_error_on_lookup_returns_503(self):
        """POST /api/centurion/tasks/{id}/cancel returns 503 on DB error during lookup."""
        db = AsyncMock()
        db.get_task = AsyncMock(side_effect=RuntimeError("connection refused"))
        engine = _mock_engine(db=db)
        app = _make_app(centurion=engine)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/centurion/tasks/task-abc123/cancel")
        assert response.status_code == 503
        assert "temporarily unavailable" in response.json()["detail"].lower()

    async def test_cancel_task_db_error_on_update_returns_503(self):
        """POST cancel returns 503 when DB fails during the update_task call."""
        db = AsyncMock()
        db.get_task = AsyncMock(return_value={"task_id": "task-abc", "status": "pending"})
        db.update_task = AsyncMock(side_effect=RuntimeError("disk full"))
        engine = _mock_engine(db=db)
        app = _make_app(centurion=engine)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/centurion/tasks/task-abc/cancel")
        assert response.status_code == 503
        assert "temporarily unavailable" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 5. Request logging middleware exists and works
# ---------------------------------------------------------------------------

class TestRequestLoggingMiddleware:
    async def test_middleware_logs_request(self, caplog):
        """The request logging middleware logs method, path, status, and duration."""
        import logging
        engine = _mock_engine(has_db=True)
        app = _make_app(centurion=engine)
        transport = ASGITransport(app=app)
        with caplog.at_level(logging.INFO, logger="centurion.api.router"):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.get("/health")
        # Check that a log record was emitted with request info
        matching = [r for r in caplog.records if "request:" in r.message and "/health" in r.message]
        assert len(matching) >= 1
        record = matching[0]
        assert "method=GET" in record.message
        assert "status=200" in record.message
        assert "duration_ms=" in record.message

    async def test_middleware_does_not_break_responses(self):
        """Middleware passes through responses unchanged."""
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
