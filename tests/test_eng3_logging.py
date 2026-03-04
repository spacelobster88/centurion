"""Tests for eng-3: structured logging in scheduler, router, agent types, and events."""

from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from centurion.config import CenturionConfig
from centurion.core.scheduler import CenturionScheduler
from centurion.core.events import EventBus
from centurion.agent_types.base import AgentResult
from tests.conftest import MockAgentType


# =========================================================================
# Scheduler logging
# =========================================================================


class TestSchedulerLogging:
    """Verify CenturionScheduler methods emit log records at DEBUG."""

    @pytest.fixture
    def scheduler(self):
        return CenturionScheduler(config=CenturionConfig())

    @pytest.fixture
    def agent(self):
        return MockAgentType()

    def test_can_schedule_logs_debug(self, scheduler, agent, caplog):
        """can_schedule() should log at DEBUG with agent_type and resource info."""
        with caplog.at_level(logging.DEBUG, logger="centurion.core.scheduler"):
            scheduler.can_schedule(agent)
        assert len(caplog.records) > 0
        record = caplog.records[0]
        assert record.levelno == logging.DEBUG
        assert "mock" in record.message.lower() or "can_schedule" in record.message.lower()

    def test_allocate_logs_debug(self, scheduler, agent, caplog):
        """allocate() should log at DEBUG with agent_type and new totals."""
        with caplog.at_level(logging.DEBUG, logger="centurion.core.scheduler"):
            scheduler.allocate(agent)
        assert len(caplog.records) > 0
        record = caplog.records[0]
        assert record.levelno == logging.DEBUG
        assert "allocat" in record.message.lower()

    def test_release_logs_debug(self, scheduler, agent, caplog):
        """release() should log at DEBUG with agent_type and new totals."""
        scheduler.allocate(agent)
        with caplog.at_level(logging.DEBUG, logger="centurion.core.scheduler"):
            caplog.clear()
            scheduler.release(agent)
        assert len(caplog.records) > 0
        record = caplog.records[0]
        assert record.levelno == logging.DEBUG
        assert "release" in record.message.lower()

    def test_probe_system_logs_debug(self, scheduler, caplog):
        """probe_system() should log at DEBUG with system resources snapshot."""
        with caplog.at_level(logging.DEBUG, logger="centurion.core.scheduler"):
            scheduler.probe_system()
        assert len(caplog.records) > 0
        record = caplog.records[0]
        assert record.levelno == logging.DEBUG
        assert "probe" in record.message.lower() or "system" in record.message.lower()


# =========================================================================
# Router logging middleware
# =========================================================================


class TestRouterLoggingMiddleware:
    """Verify router.py has request logging middleware."""

    def test_router_has_logger(self):
        """router.py should define a module-level logger."""
        import centurion.api.router as router_mod
        assert hasattr(router_mod, "logger")
        assert isinstance(router_mod.logger, logging.Logger)

    def test_router_has_logging_middleware(self):
        """router.py should define a request_logging_middleware function."""
        import centurion.api.router as router_mod
        assert hasattr(router_mod, "request_logging_middleware")
        assert callable(router_mod.request_logging_middleware)

    @pytest.mark.asyncio
    async def test_middleware_logs_request(self, caplog):
        """The middleware should log method, path, status_code, duration_ms at INFO."""
        from centurion.api.router import request_logging_middleware

        # Build a mock request/response pair
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/api/centurion/status"

        mock_response = MagicMock()
        mock_response.status_code = 200

        async def mock_call_next(req):
            return mock_response

        with caplog.at_level(logging.DEBUG, logger="centurion.api.router"):
            response = await request_logging_middleware(mock_request, mock_call_next)

        assert response == mock_response
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(info_records) >= 1
        msg = info_records[0].message
        assert "GET" in msg
        assert "/api/centurion/status" in msg
        assert "200" in msg
        assert "duration" in msg.lower() or "ms" in msg.lower()

    @pytest.mark.asyncio
    async def test_middleware_warns_on_error_status(self, caplog):
        """The middleware should log at WARNING for 4xx/5xx responses."""
        from centurion.api.router import request_logging_middleware

        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url.path = "/api/centurion/legions"

        mock_response = MagicMock()
        mock_response.status_code = 500

        async def mock_call_next(req):
            return mock_response

        with caplog.at_level(logging.DEBUG, logger="centurion.api.router"):
            await request_logging_middleware(mock_request, mock_call_next)

        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warn_records) >= 1
        assert "500" in warn_records[0].message


# =========================================================================
# Agent type logging — Claude CLI
# =========================================================================


class TestClaudeCliLogging:
    """Verify claude_cli.py emits log records on send_task."""

    def test_claude_cli_has_logger(self):
        """claude_cli.py should define a module-level logger."""
        import centurion.agent_types.claude_cli as mod
        assert hasattr(mod, "logger")
        assert isinstance(mod.logger, logging.Logger)

    @pytest.mark.asyncio
    async def test_send_task_logs_debug_start(self, caplog):
        """send_task() should log at DEBUG on task start with legionary_id and cwd."""
        from centurion.agent_types.claude_cli import ClaudeCliAgentType

        agent = ClaudeCliAgentType(binary="echo")  # use echo to avoid real CLI
        handle = {"legionary_id": "leg-001", "cwd": "/tmp", "env": {}}

        with caplog.at_level(logging.DEBUG, logger="centurion.agent_types.claude_cli"):
            # It will fail or succeed quickly with echo
            result = await agent.send_task(handle, "hello", timeout=5.0)

        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1
        assert "leg-001" in debug_records[0].message

    @pytest.mark.asyncio
    async def test_send_task_logs_info_completion(self, caplog):
        """send_task() should log at INFO on completion with duration and exit_code."""
        from centurion.agent_types.claude_cli import ClaudeCliAgentType

        agent = ClaudeCliAgentType(binary="echo")
        handle = {"legionary_id": "leg-001", "cwd": "/tmp", "env": {}}

        with caplog.at_level(logging.DEBUG, logger="centurion.agent_types.claude_cli"):
            result = await agent.send_task(handle, "hello", timeout=5.0)

        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(info_records) >= 1
        msg = info_records[0].message
        assert "duration" in msg.lower() or "exit_code" in msg.lower() or "completed" in msg.lower()

    @pytest.mark.asyncio
    async def test_send_task_logs_warning_on_timeout(self, caplog):
        """send_task() should log at WARNING on timeout."""
        from centurion.agent_types.claude_cli import ClaudeCliAgentType

        agent = ClaudeCliAgentType(binary="sleep")
        handle = {"legionary_id": "leg-timeout", "cwd": "/tmp", "env": {}}

        with caplog.at_level(logging.DEBUG, logger="centurion.agent_types.claude_cli"):
            result = await agent.send_task(handle, "100", timeout=0.1)

        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warn_records) >= 1
        assert "timeout" in warn_records[0].message.lower()


# =========================================================================
# Agent type logging — Claude API
# =========================================================================


class TestClaudeApiLogging:
    """Verify claude_api.py emits log records on send_task."""

    def test_claude_api_has_logger(self):
        """claude_api.py should define a module-level logger."""
        import centurion.agent_types.claude_api as mod
        assert hasattr(mod, "logger")
        assert isinstance(mod.logger, logging.Logger)

    @pytest.mark.asyncio
    async def test_send_task_logs_debug_start(self, caplog):
        """send_task() should log at DEBUG on task start with model, max_tokens."""
        from centurion.agent_types.claude_api import ClaudeApiAgentType

        agent = ClaudeApiAgentType(model="test-model", max_tokens=100, api_key="fake-key")
        handle = {"legionary_id": "leg-api-001", "api_key": "fake-key"}

        with caplog.at_level(logging.DEBUG, logger="centurion.agent_types.claude_api"):
            # This will fail (no real API), which is fine — we just want to check logging
            result = await agent.send_task(handle, "hello", timeout=5.0)

        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1
        assert "test-model" in debug_records[0].message or "model" in debug_records[0].message.lower()

    @pytest.mark.asyncio
    async def test_send_task_logs_warning_on_failure(self, caplog):
        """send_task() should log at WARNING on failure."""
        from centurion.agent_types.claude_api import ClaudeApiAgentType

        agent = ClaudeApiAgentType(model="test-model", max_tokens=100, api_key="fake-key")
        handle = {"legionary_id": "leg-api-001", "api_key": "fake-key"}

        with caplog.at_level(logging.DEBUG, logger="centurion.agent_types.claude_api"):
            result = await agent.send_task(handle, "hello", timeout=5.0)

        # Should warn since API call will fail
        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warn_records) >= 1


# =========================================================================
# Agent type logging — Shell
# =========================================================================


class TestShellLogging:
    """Verify shell.py emits log records on send_task."""

    def test_shell_has_logger(self):
        """shell.py should define a module-level logger."""
        import centurion.agent_types.shell as mod
        assert hasattr(mod, "logger")
        assert isinstance(mod.logger, logging.Logger)

    @pytest.mark.asyncio
    async def test_send_task_logs_debug_start(self, caplog):
        """send_task() should log at DEBUG on task start with shell and cwd."""
        from centurion.agent_types.shell import ShellAgentType

        agent = ShellAgentType(shell="/bin/sh")
        handle = {"legionary_id": "leg-shell-001", "cwd": "/tmp", "env": {}}

        with caplog.at_level(logging.DEBUG, logger="centurion.agent_types.shell"):
            result = await agent.send_task(handle, "echo hello", timeout=5.0)

        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1
        assert "shell" in debug_records[0].message.lower() or "/bin/sh" in debug_records[0].message

    @pytest.mark.asyncio
    async def test_send_task_logs_info_completion(self, caplog):
        """send_task() should log at INFO on completion with duration and exit_code."""
        from centurion.agent_types.shell import ShellAgentType

        agent = ShellAgentType(shell="/bin/sh")
        handle = {"legionary_id": "leg-shell-001", "cwd": "/tmp", "env": {}}

        with caplog.at_level(logging.DEBUG, logger="centurion.agent_types.shell"):
            result = await agent.send_task(handle, "echo hello", timeout=5.0)

        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(info_records) >= 1
        msg = info_records[0].message
        assert "duration" in msg.lower() or "exit_code" in msg.lower() or "completed" in msg.lower()

    @pytest.mark.asyncio
    async def test_send_task_logs_warning_on_timeout(self, caplog):
        """send_task() should log at WARNING on timeout."""
        from centurion.agent_types.shell import ShellAgentType

        agent = ShellAgentType(shell="/bin/sh")
        handle = {"legionary_id": "leg-shell-timeout", "cwd": "/tmp", "env": {}}

        with caplog.at_level(logging.DEBUG, logger="centurion.agent_types.shell"):
            result = await agent.send_task(handle, "sleep 100", timeout=0.1)

        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warn_records) >= 1
        assert "timeout" in warn_records[0].message.lower()


# =========================================================================
# EventBus logging
# =========================================================================


class TestEventBusLogging:
    """Verify EventBus methods emit log records."""

    def test_events_has_logger(self):
        """events.py should define a module-level logger."""
        import centurion.core.events as mod
        assert hasattr(mod, "logger")
        assert isinstance(mod.logger, logging.Logger)

    @pytest.mark.asyncio
    async def test_emit_logs_debug(self, caplog):
        """emit() should log at DEBUG with event_type, entity_type, entity_id."""
        bus = EventBus()
        with caplog.at_level(logging.DEBUG, logger="centurion.core.events"):
            await bus.emit("task.started", entity_type="legionary", entity_id="leg-001")

        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1
        msg = debug_records[0].message
        assert "task.started" in msg
        assert "legionary" in msg
        assert "leg-001" in msg

    def test_subscribe_logs_debug(self, caplog):
        """subscribe() should log at DEBUG about new subscriber."""
        bus = EventBus()
        with caplog.at_level(logging.DEBUG, logger="centurion.core.events"):
            bus.subscribe()

        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1
        assert "subscrib" in debug_records[0].message.lower()

    def test_unsubscribe_logs_debug(self, caplog):
        """unsubscribe() should log at DEBUG about subscriber removal."""
        bus = EventBus()
        queue = bus.subscribe()
        with caplog.at_level(logging.DEBUG, logger="centurion.core.events"):
            caplog.clear()
            bus.unsubscribe(queue)

        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1
        assert "unsubscrib" in debug_records[0].message.lower() or "removed" in debug_records[0].message.lower()

    @pytest.mark.asyncio
    async def test_emit_warns_on_queue_full(self, caplog):
        """emit() should log at WARNING when a queue is full (event dropped)."""
        bus = EventBus()
        # Create a queue with max size 1 and fill it
        small_queue = asyncio.Queue(maxsize=1)
        bus._subscribers.append(small_queue)
        await small_queue.put("filler")  # fill the queue

        with caplog.at_level(logging.DEBUG, logger="centurion.core.events"):
            await bus.emit("task.overflow", entity_type="test", entity_id="t-001")

        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warn_records) >= 1
        assert "drop" in warn_records[0].message.lower() or "full" in warn_records[0].message.lower()
