"""Tests for Legionary lifecycle and task execution."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from centurion.agent_types.base import AgentResult
from centurion.core.exceptions import AgentProcessError, TaskTimeoutError
from centurion.core.legionary import Legionary, LegionaryStatus, MAX_CONSECUTIVE_FAILURES
from centurion.core.session_registry import SessionRegistry


async def test_create_legionary(mock_agent_type):
    """A freshly created legionary has correct defaults."""
    leg = Legionary(agent_type=mock_agent_type, century_id="cent-test")

    assert leg.id.startswith("leg-")
    assert leg.century_id == "cent-test"
    assert leg.status == LegionaryStatus.IDLE
    assert leg.tasks_completed == 0
    assert leg.tasks_failed == 0
    assert leg.consecutive_failures == 0
    assert leg.current_task_id is None
    assert leg.handle is None


async def test_execute_success(mock_agent_type):
    """Successful task execution updates counters and returns to IDLE."""
    leg = Legionary(agent_type=mock_agent_type, century_id="cent-test")
    leg.handle = await mock_agent_type.spawn(leg.id, "/tmp", {})

    result = await leg.execute("task-001", "Say hello", timeout=10.0)

    assert result.success is True
    assert "Mock result for: Say hello" in result.output
    assert result.task_id == "task-001"
    assert result.legionary_id == leg.id
    assert leg.tasks_completed == 1
    assert leg.tasks_failed == 0
    assert leg.consecutive_failures == 0
    assert leg.status == LegionaryStatus.IDLE
    assert leg.current_task_id is None
    assert leg.total_duration > 0


async def test_execute_failure(failing_agent_type):
    """Failed task execution increments failure counters."""
    leg = Legionary(agent_type=failing_agent_type, century_id="cent-test")
    leg.handle = await failing_agent_type.spawn(leg.id, "/tmp", {})

    result = await leg.execute("task-002", "This will fail", timeout=10.0)

    assert result.success is False
    assert leg.tasks_completed == 0
    assert leg.tasks_failed == 1
    assert leg.consecutive_failures == 1
    assert leg.status == LegionaryStatus.IDLE


async def test_needs_replacement(failing_agent_type):
    """After MAX_CONSECUTIVE_FAILURES failures, the legionary needs replacement."""
    leg = Legionary(agent_type=failing_agent_type, century_id="cent-test")
    leg.handle = await failing_agent_type.spawn(leg.id, "/tmp", {})

    assert leg.needs_replacement is False

    for i in range(MAX_CONSECUTIVE_FAILURES):
        await leg.execute(f"task-{i}", "fail", timeout=10.0)

    assert leg.consecutive_failures == MAX_CONSECUTIVE_FAILURES
    assert leg.needs_replacement is True


async def test_status_after_success_resets_failures(mock_agent_type):
    """A successful task resets consecutive_failures to zero."""
    leg = Legionary(agent_type=mock_agent_type, century_id="cent-test")
    leg.handle = await mock_agent_type.spawn(leg.id, "/tmp", {})

    # Simulate some failures by manually setting the counter
    leg.consecutive_failures = 2
    leg.tasks_failed = 2

    result = await leg.execute("task-reset", "Succeed now", timeout=10.0)

    assert result.success is True
    assert leg.consecutive_failures == 0
    assert leg.tasks_completed == 1
    # tasks_failed remains at 2 (historical count, not reset)
    assert leg.tasks_failed == 2


# --- S1-S5 error handling tests ---


async def test_legionary_timeout_raises_task_timeout_error(mock_agent_type):
    """When agent_type.send_task raises asyncio.TimeoutError, Legionary raises TaskTimeoutError."""
    leg = Legionary(agent_type=mock_agent_type, century_id="cent-test")
    leg.handle = await mock_agent_type.spawn(leg.id, "/tmp", {})

    # Mock send_task to raise asyncio.TimeoutError
    mock_agent_type.send_task = AsyncMock(side_effect=asyncio.TimeoutError())

    with pytest.raises(TaskTimeoutError) as exc_info:
        await leg.execute("task-timeout", "This will time out", timeout=5.0)

    exc = exc_info.value
    assert exc.timeout_seconds == 5.0
    assert exc.retryable is True
    assert leg.tasks_failed == 1
    assert leg.consecutive_failures == 1
    # Timeout is transient -- legionary should still be IDLE, not FAILED
    assert leg.status == LegionaryStatus.IDLE


async def test_legionary_crash_exit_code_raises_agent_process_error(mock_agent_type):
    """When agent returns a crash exit code (e.g. -9), Legionary raises AgentProcessError."""
    leg = Legionary(agent_type=mock_agent_type, century_id="cent-test")
    leg.handle = await mock_agent_type.spawn(leg.id, "/tmp", {})

    # Mock send_task to return a failed result with crash exit code
    mock_agent_type.send_task = AsyncMock(
        return_value=AgentResult(
            success=False,
            output="",
            error="Killed by signal 9",
            exit_code=-9,
            duration_seconds=0.5,
        )
    )

    with pytest.raises(AgentProcessError) as exc_info:
        await leg.execute("task-crash", "This will crash", timeout=10.0)

    exc = exc_info.value
    assert exc.exit_code == -9
    assert exc.retryable is True  # -9 is in TRANSIENT_EXIT_CODES
    # tasks_failed is incremented once in the non-success branch and once in
    # the except AgentProcessError handler, so the total is 2.
    assert leg.tasks_failed == 2
    assert leg.consecutive_failures == 2


async def test_legionary_success_resets_failures(mock_agent_type):
    """A successful execute() resets consecutive_failures to 0."""
    leg = Legionary(agent_type=mock_agent_type, century_id="cent-test")
    leg.handle = await mock_agent_type.spawn(leg.id, "/tmp", {})

    # Accumulate some failures first
    leg.consecutive_failures = 2
    leg.tasks_failed = 2

    result = await leg.execute("task-ok", "This succeeds", timeout=10.0)

    assert result.success is True
    assert leg.consecutive_failures == 0
    assert leg.tasks_completed == 1


async def test_legionary_failed_status_on_non_retryable_error(mock_agent_type):
    """Non-retryable AgentProcessError sets legionary status to FAILED."""
    leg = Legionary(agent_type=mock_agent_type, century_id="cent-test")
    leg.handle = await mock_agent_type.spawn(leg.id, "/tmp", {})

    # Mock send_task to raise a non-retryable AgentProcessError
    # exit_code=1 is NOT in TRANSIENT_EXIT_CODES, so retryable=False
    mock_agent_type.send_task = AsyncMock(
        side_effect=AgentProcessError(
            "Fatal process error",
            exit_code=1,
            stderr="segfault",
        )
    )

    with pytest.raises(AgentProcessError) as exc_info:
        await leg.execute("task-fatal", "This fails fatally", timeout=10.0)

    exc = exc_info.value
    assert exc.retryable is False
    assert leg.status == LegionaryStatus.FAILED
    assert leg.tasks_failed == 1
    assert leg.consecutive_failures == 1


# ---------------------------------------------------------------------------
# to_dict with session_registry
# ---------------------------------------------------------------------------

class TestToDictCloseableFields:
    def test_to_dict_without_registry(self, mock_agent_type):
        """Without a registry, to_dict should NOT include closeable fields."""
        leg = Legionary(agent_type=mock_agent_type, century_id="cent-test")
        d = leg.to_dict()
        assert "has_bg_children" not in d
        assert "bg_child_ids" not in d
        assert "closeable" not in d

    def test_to_dict_with_registry_no_children(self, mock_agent_type):
        """With a registry and no children, closeable fields should be present."""
        reg = SessionRegistry()
        reg.register_session("leg-1", parent_id=None, session_type="interactive")
        leg = Legionary(id="leg-1", agent_type=mock_agent_type, century_id="cent-test")
        d = leg.to_dict(session_registry=reg)
        assert d["has_bg_children"] is False
        assert d["bg_child_ids"] == []
        assert d["closeable"] is True

    def test_to_dict_with_registry_active_children(self, mock_agent_type):
        """With active background children, closeable should be False."""
        reg = SessionRegistry()
        reg.register_session("leg-p", parent_id=None, session_type="interactive")
        reg.register_session("leg-c", parent_id="leg-p", session_type="background")
        leg = Legionary(id="leg-p", agent_type=mock_agent_type, century_id="cent-test")
        d = leg.to_dict(session_registry=reg)
        assert d["has_bg_children"] is True
        assert d["bg_child_ids"] == ["leg-c"]
        assert d["closeable"] is False
