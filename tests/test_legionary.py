"""Tests for Legionary lifecycle and task execution."""

import pytest

from centurion.core.legionary import Legionary, LegionaryStatus, MAX_CONSECUTIVE_FAILURES


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
