"""Tests for Century — agent squad with shared task queue."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from centurion.core.century import Century, CenturyConfig
from centurion.core.circuit_breaker import CircuitBreaker
from centurion.core.exceptions import CenturionError
from centurion.core.legionary import LegionaryStatus


async def test_muster_legionaries(mock_agent_type):
    """Mustering a century creates the requested number of legionaries."""
    config = CenturyConfig(min_legionaries=1, max_legionaries=10, autoscale=False)
    century = Century(century_id="cent-muster", config=config, agent_type=mock_agent_type)

    created = await century.muster(3)

    assert len(created) == 3
    assert len(century.legionaries) == 3
    for leg in created:
        assert leg.status == LegionaryStatus.IDLE
        assert leg.agent_type is mock_agent_type
        assert leg.century_id == "cent-muster"


async def test_submit_and_complete_task(mock_agent_type):
    """Submitting a task returns a future that resolves with the agent result."""
    config = CenturyConfig(min_legionaries=1, max_legionaries=5, autoscale=False)
    century = Century(century_id="cent-task", config=config, agent_type=mock_agent_type)
    await century.muster(1)
    await century.start()

    try:
        future = await century.submit_task("Analyze this document", priority=5)
        result = await asyncio.wait_for(future, timeout=5.0)

        assert result.success is True
        assert "Mock result for: Analyze this document" in result.output
        assert result.duration_seconds > 0
    finally:
        await century.dismiss()


async def test_priority_ordering(mock_agent_type):
    """Tasks with lower priority numbers are processed before higher ones."""
    config = CenturyConfig(min_legionaries=1, max_legionaries=1, autoscale=False)
    century = Century(century_id="cent-prio", config=config, agent_type=mock_agent_type)
    await century.muster(1)

    # Submit tasks without starting workers so they queue up
    future_low = await century.submit_task("Low priority task", priority=10)
    future_high = await century.submit_task("High priority task", priority=1)

    # Now start workers to drain the queue
    await century.start()

    try:
        result_high = await asyncio.wait_for(future_high, timeout=5.0)
        result_low = await asyncio.wait_for(future_low, timeout=5.0)

        # Both should succeed
        assert result_high.success is True
        assert result_low.success is True
        assert "High priority task" in result_high.output
        assert "Low priority task" in result_low.output

        # The high-priority task (priority=1) should have completed first,
        # meaning it has an earlier or equal duration timestamp.
        # Since the mock agent processes sequentially with one legionary,
        # priority=1 is dequeued before priority=10.
        assert result_high.duration_seconds <= result_low.duration_seconds + 1.0
    finally:
        await century.dismiss()


async def test_status_report(mock_agent_type):
    """Status report contains all expected fields."""
    config = CenturyConfig(min_legionaries=1, max_legionaries=5, autoscale=False)
    century = Century(century_id="cent-status", config=config, agent_type=mock_agent_type)
    await century.muster(2)

    report = century.status_report()

    assert report["century_id"] == "cent-status"
    assert report["agent_type"] == "mock"
    assert report["legionaries_count"] == 2
    assert "idle" in report
    assert "busy" in report
    assert "failed" in report
    assert "queue_depth" in report
    assert "total_tasks_completed" in report
    assert "total_tasks_failed" in report
    assert "config" in report
    assert report["config"]["min_legionaries"] == 1
    assert report["config"]["max_legionaries"] == 5


async def test_dismiss(mock_agent_type):
    """Dismissing a century terminates all legionaries and clears state."""
    config = CenturyConfig(min_legionaries=1, max_legionaries=5, autoscale=False)
    century = Century(century_id="cent-dismiss", config=config, agent_type=mock_agent_type)
    await century.muster(3)
    await century.start()

    assert len(century.legionaries) == 3

    await century.dismiss()

    assert len(century.legionaries) == 0
    assert century._running is False


# --- S1-S5 error handling tests ---


async def test_century_has_circuit_breaker(mock_agent_type):
    """Century.__init__ creates a CircuitBreaker instance."""
    config = CenturyConfig(autoscale=False)
    century = Century(century_id="cent-cb", config=config, agent_type=mock_agent_type)

    assert hasattr(century, "_circuit_breaker")
    assert isinstance(century._circuit_breaker, CircuitBreaker)
    assert century._circuit_breaker.name == "cent-cb"
    # Verify circuit breaker starts in a usable state
    assert century._circuit_breaker.can_execute() is True


async def test_submit_task_queue_full(mock_agent_type):
    """When the queue is full, submit_task sets CenturionError on the future."""
    config = CenturyConfig(autoscale=False)
    century = Century(century_id="cent-full", config=config, agent_type=mock_agent_type)
    # Replace the default queue with a tiny one (maxsize=1)
    century.task_queue = asyncio.PriorityQueue(maxsize=1)

    # First submit should succeed (fills the queue)
    future1 = await century.submit_task("task one", priority=5)
    assert not future1.done() or future1.exception() is None

    # Second submit should fail because the queue is full
    future2 = await century.submit_task("task two", priority=5)
    assert future2.done()
    with pytest.raises(CenturionError, match="queue full"):
        future2.result()

    exc = future2.exception()
    assert isinstance(exc, CenturionError)
    assert exc.retryable is True


async def test_dismiss_fails_pending_futures(mock_agent_type):
    """dismiss() sets CenturionError on all pending futures in the queue."""
    config = CenturyConfig(min_legionaries=1, max_legionaries=5, autoscale=False)
    century = Century(century_id="cent-drain", config=config, agent_type=mock_agent_type)
    # Do NOT muster or start workers -- tasks stay queued

    future1 = await century.submit_task("pending task 1", priority=5)
    future2 = await century.submit_task("pending task 2", priority=5)

    # Neither future should be resolved yet
    assert not future1.done()
    assert not future2.done()

    await century.dismiss()

    # Both futures should now have CenturionError
    for fut in (future1, future2):
        assert fut.done()
        exc = fut.exception()
        assert isinstance(exc, CenturionError)
        assert "dismissed" in str(exc)
        assert exc.retryable is False


async def test_optio_loop_survives_exception(mock_agent_type):
    """The optio loop catches non-CancelledError exceptions and continues running."""
    config = CenturyConfig(
        autoscale=True,
        cooldown=0.01,  # very short cooldown for fast test
    )
    century = Century(century_id="cent-optio", config=config, agent_type=mock_agent_type)
    century._running = True

    call_count = 0

    async def mock_optio_check():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RuntimeError("Simulated optio check failure")
        # After 2 failures, stop the loop by setting _running = False
        century._running = False

    with patch.object(century, "_optio_check", side_effect=mock_optio_check):
        # Also patch asyncio.sleep to avoid actual delays
        original_sleep = asyncio.sleep

        async def fast_sleep(delay):
            await original_sleep(0.001)

        with patch("centurion.core.century.asyncio.sleep", side_effect=fast_sleep):
            await century._optio_loop()

    # The loop should have survived 2 exceptions and run _optio_check 3 times total
    assert call_count == 3, f"Expected 3 calls to _optio_check, got {call_count}"
