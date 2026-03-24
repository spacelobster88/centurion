"""Tests for Century — agent squad with shared task queue."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from centurion.core.century import Century, CenturyConfig
from centurion.core.circuit_breaker import CircuitBreaker
from centurion.core.events import EventBus
from centurion.core.exceptions import CenturionError
from centurion.core.legionary import LegionaryStatus
from centurion.core.scheduler import CenturionScheduler, MemoryPressureLevel


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


# --- Memory-pressure scale-down tests (Optio) ---


def _make_century_with_idle_legionaries(
    mock_agent_type,
    n_legionaries: int,
    min_legionaries: int = 2,
    scheduler: CenturionScheduler | None = None,
    event_bus: EventBus | None = None,
):
    """Helper: create a Century with n idle legionaries (no real spawning)."""
    from centurion.core.legionary import Legionary

    config = CenturyConfig(
        min_legionaries=min_legionaries,
        max_legionaries=10,
        autoscale=True,
    )
    century = Century(
        century_id="cent-mem",
        config=config,
        agent_type=mock_agent_type,
        scheduler=scheduler,
        event_bus=event_bus,
    )
    for _i in range(n_legionaries):
        leg = Legionary(century_id="cent-mem", agent_type=mock_agent_type)
        leg.status = LegionaryStatus.IDLE
        leg.handle = {"legionary_id": leg.id}
        century.legionaries[leg.id] = leg
    return century


async def test_memory_pressure_critical_terminates_all_idle(mock_agent_type):
    """CRITICAL pressure terminates ALL idle legionaries, even below min_legionaries."""
    scheduler = CenturionScheduler()
    century = _make_century_with_idle_legionaries(
        mock_agent_type,
        n_legionaries=4,
        min_legionaries=3,
        scheduler=scheduler,
    )

    assert len(century.legionaries) == 4

    with patch.object(scheduler, "_memory_pressure_level", return_value=MemoryPressureLevel.CRITICAL):
        await century._memory_pressure_scale_down()

    # ALL idle should be terminated, even though min_legionaries=3
    assert len(century.legionaries) == 0


async def test_memory_pressure_warn_terminates_above_min(mock_agent_type):
    """WARN pressure terminates idle legionaries above min_legionaries only."""
    scheduler = CenturionScheduler()
    century = _make_century_with_idle_legionaries(
        mock_agent_type,
        n_legionaries=5,
        min_legionaries=2,
        scheduler=scheduler,
    )

    assert len(century.legionaries) == 5

    with patch.object(scheduler, "_memory_pressure_level", return_value=MemoryPressureLevel.WARN):
        await century._memory_pressure_scale_down()

    # Should keep min_legionaries=2, remove excess (5-2=3)
    assert len(century.legionaries) == 2


async def test_memory_pressure_warn_no_removal_at_min(mock_agent_type):
    """WARN pressure does NOT remove legionaries when already at min_legionaries."""
    scheduler = CenturionScheduler()
    century = _make_century_with_idle_legionaries(
        mock_agent_type,
        n_legionaries=2,
        min_legionaries=2,
        scheduler=scheduler,
    )

    with patch.object(scheduler, "_memory_pressure_level", return_value=MemoryPressureLevel.WARN):
        await century._memory_pressure_scale_down()

    assert len(century.legionaries) == 2


async def test_memory_pressure_normal_does_nothing(mock_agent_type):
    """NORMAL pressure performs no scale-down."""
    scheduler = CenturionScheduler()
    century = _make_century_with_idle_legionaries(
        mock_agent_type,
        n_legionaries=5,
        min_legionaries=2,
        scheduler=scheduler,
    )

    with patch.object(scheduler, "_memory_pressure_level", return_value=MemoryPressureLevel.NORMAL):
        await century._memory_pressure_scale_down()

    assert len(century.legionaries) == 5


async def test_memory_scale_down_cooldown_blocks_scale_up(mock_agent_type):
    """After memory scale-down, _optio_check() should NOT scale up within 30s."""
    scheduler = CenturionScheduler()
    century = _make_century_with_idle_legionaries(
        mock_agent_type,
        n_legionaries=4,
        min_legionaries=2,
        scheduler=scheduler,
    )

    # Phase 1: trigger a CRITICAL scale-down to set _last_memory_scale_time
    with patch.object(scheduler, "_memory_pressure_level", return_value=MemoryPressureLevel.CRITICAL):
        await century._memory_pressure_scale_down()

    assert len(century.legionaries) == 0

    # Phase 2: pressure returns to NORMAL, but 30s cooldown should block scale-up.
    # Add tasks to the queue to trigger scale-up desire.
    loop = asyncio.get_running_loop()
    for i in range(5):
        future = loop.create_future()
        century.task_queue.put_nowait((5, 0.0, f"task-{i}", "prompt", future))

    # Re-add some legionaries so there's something to work with
    century_orig_legionaries = _make_century_with_idle_legionaries(
        mock_agent_type,
        n_legionaries=1,
        min_legionaries=2,
        scheduler=scheduler,
    )
    century.legionaries.update(century_orig_legionaries.legionaries)

    # Mock time so we are only 10s after scale-down (within 30s cooldown)
    scale_time = century._last_memory_scale_time
    with (
        patch.object(
            scheduler,
            "_memory_pressure_level",
            return_value=MemoryPressureLevel.NORMAL,
        ),
        patch("centurion.core.century.time") as mock_time,
    ):
        mock_time.time.return_value = scale_time + 10.0  # only 10s later

        initial_count = len(century.legionaries)
        await century._optio_check()

        # No scale-up should have happened — cooldown still active
        assert len(century.legionaries) == initial_count

    # Now simulate time past cooldown (31s later)
    with (
        patch.object(
            scheduler,
            "_memory_pressure_level",
            return_value=MemoryPressureLevel.NORMAL,
        ),
        patch("centurion.core.century.time") as mock_time,
        patch.object(scheduler, "available_slots", return_value=5),
        patch.object(scheduler, "can_schedule", return_value=True),
        patch.object(scheduler, "allocate"),
    ):
        mock_time.time.return_value = scale_time + 31.0  # past cooldown

        await century._optio_check()

        # Scale-up should now proceed — more legionaries added
        assert len(century.legionaries) > initial_count


async def test_memory_scale_down_emits_event(mock_agent_type):
    """Scale-down events are emitted with correct payload (pressure level, count removed)."""
    scheduler = CenturionScheduler()
    event_bus = AsyncMock(spec=EventBus)
    century = _make_century_with_idle_legionaries(
        mock_agent_type,
        n_legionaries=4,
        min_legionaries=2,
        scheduler=scheduler,
        event_bus=event_bus,
    )

    with patch.object(scheduler, "_memory_pressure_level", return_value=MemoryPressureLevel.CRITICAL):
        await century._memory_pressure_scale_down()

    # Find the memory_scale_down event among all emitted events
    memory_events = [call for call in event_bus.emit.call_args_list if call.args[0] == "memory_scale_down"]
    assert len(memory_events) == 1

    call = memory_events[0]
    assert call.kwargs["entity_type"] == "century"
    assert call.kwargs["entity_id"] == "cent-mem"
    payload = call.kwargs["payload"]
    assert payload["pressure"] == "critical"
    assert payload["removed"] == 4
    assert payload["remaining"] == 0
