"""Tests for the POST /api/centurion/purge endpoint and Throttle._attempt_purge."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from centurion.api.router import health_router, request_logging_middleware, router
from centurion.hardware.throttle import Throttle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> FastAPI:
    """Create a minimal FastAPI app wired with both routers and a mock engine."""
    app = FastAPI()
    app.middleware("http")(request_logging_middleware)
    app.include_router(health_router)
    app.include_router(router)
    # The router expects app.state.centurion to exist for some endpoints.
    app.state.centurion = MagicMock()
    return app


# =========================================================================
# Purge endpoint — POST /api/centurion/purge
# =========================================================================


class TestPurgeEndpointSuccess:
    """Returns {"status": "ok"} when sudo purge succeeds on macOS."""

    @patch("subprocess.run")
    @patch("platform.system", return_value="Darwin")
    async def test_returns_ok_on_success(self, mock_system, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/centurion/purge")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"


class TestPurgeEndpointSkipped:
    """Returns {"status": "skipped"} on non-macOS platforms."""

    @patch("platform.system", return_value="Linux")
    async def test_skipped_on_linux(self, mock_system):
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/centurion/purge")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "skipped"
        assert body["reason"] == "not macOS"


class TestPurgeEndpointFailed:
    """Returns {"status": "failed"} when subprocess returns non-zero."""

    @patch("subprocess.run")
    @patch("platform.system", return_value="Darwin")
    async def test_returns_failed_on_nonzero(self, mock_system, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr=b"sudo: a password is required")

        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/centurion/purge")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["returncode"] == 1


class TestPurgeEndpointError:
    """Returns {"status": "error"} when subprocess raises an exception."""

    @patch("subprocess.run", side_effect=OSError("not found"))
    @patch("platform.system", return_value="Darwin")
    async def test_returns_error_on_exception(self, mock_system, mock_run):
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/centurion/purge")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "error"
        assert "not found" in body["message"]


# =========================================================================
# Throttle._attempt_purge — direct unit tests
# =========================================================================


def _make_throttle_for_purge() -> Throttle:
    """Build a Throttle instance with minimal mocked dependencies."""
    from centurion.core.scheduler import CenturionScheduler, MemoryPressureLevel, SystemResources
    from centurion.config import CenturionConfig

    config = CenturionConfig()
    config.ram_headroom_gb = 2.0

    scheduler = MagicMock(spec=CenturionScheduler)
    scheduler.config = config
    scheduler.active_agents = 0
    scheduler.recommended_max_agents.return_value = 10
    scheduler._memory_pressure_level.return_value = MemoryPressureLevel.NORMAL
    scheduler.probe_system.return_value = SystemResources(
        cpu_count=8,
        ram_total_mb=16384,
        ram_available_mb=8192,
        memory_pressure=MemoryPressureLevel.NORMAL,
    )

    event_bus = MagicMock()
    return Throttle(scheduler=scheduler, event_bus=event_bus)


class TestAttemptPurgeNonZero:
    """_attempt_purge logs a warning when returncode != 0."""

    @patch("centurion.hardware.throttle.platform")
    @patch("centurion.hardware.throttle.subprocess.run")
    def test_nonzero_returncode_logs_warning(self, mock_run, mock_platform, caplog):
        import logging

        mock_platform.system.return_value = "Darwin"
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr=b"sudo: a password is required",
        )

        throttle = _make_throttle_for_purge()
        with caplog.at_level(logging.WARNING, logger="centurion.hardware.throttle"):
            throttle._attempt_purge()

        mock_run.assert_called_once()
        warning_records = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING and "purge" in r.message.lower()
        ]
        assert len(warning_records) >= 1


class TestAttemptPurgeTimeout:
    """_attempt_purge handles subprocess timeout gracefully (no crash)."""

    @patch("centurion.hardware.throttle.platform")
    @patch(
        "centurion.hardware.throttle.subprocess.run",
        side_effect=TimeoutError("Command timed out"),
    )
    def test_timeout_handled_gracefully(self, mock_run, mock_platform, caplog):
        import logging

        mock_platform.system.return_value = "Darwin"

        throttle = _make_throttle_for_purge()
        # Must not raise
        with caplog.at_level(logging.WARNING, logger="centurion.hardware.throttle"):
            throttle._attempt_purge()

        mock_run.assert_called_once()
        warning_records = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING and "purge" in r.message.lower()
        ]
        assert len(warning_records) >= 1
