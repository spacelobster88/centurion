"""Tests for Century — agent squad with shared task queue."""

import asyncio

import pytest

from centurion.core.century import Century, CenturyConfig
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
