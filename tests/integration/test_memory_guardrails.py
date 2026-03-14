"""Integration test — full memory guardrail flow across scheduler, throttle, and century.

Exercises the complete NORMAL -> WARN -> CRITICAL -> NORMAL pressure cycle,
verifying that admission control, throttle alerts, and century scale-down
all behave correctly at each transition.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from centurion.agent_types.base import AgentResult, AgentType
from centurion.config import CenturionConfig, ResourceRequirements, ResourceSpec
from centurion.core.century import Century, CenturyConfig
from centurion.core.events import EventBus
from centurion.core.legionary import LegionaryStatus
from centurion.core.scheduler import CenturionScheduler, MemoryPressureLevel
from centurion.hardware.throttle import Throttle


# ---------------------------------------------------------------------------
# Mock agent type — lightweight, no real processes
# ---------------------------------------------------------------------------

class MockAgentType(AgentType):
    """Deterministic mock agent for guardrail integration tests."""

    name = "mock_guardrail"

    async def spawn(self, legionary_id, cwd, env):
        return {"legionary_id": legionary_id}

    async def send_task(self, handle, task, timeout):
        await asyncio.sleep(0.001)
        return AgentResult(success=True, output="ok", duration_seconds=0.001)

    async def stream_output(self, handle):
        return
        yield  # async generator

    async def terminate(self, handle, graceful=True):
        pass

    def resource_requirements(self):
        return ResourceRequirements(
            requests=ResourceSpec(cpu_millicores=10, memory_mb=10),
            limits=ResourceSpec(cpu_millicores=10, memory_mb=10),
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def agent_type():
    return MockAgentType()


@pytest.fixture
def config():
    return CenturionConfig(
        max_agents_hard_limit=20,
        ram_headroom_gb=0.5,
    )


@pytest.fixture
def scheduler(config):
    return CenturionScheduler(config=config)


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def throttle(scheduler, event_bus):
    return Throttle(scheduler=scheduler, event_bus=event_bus)


@pytest.fixture
def century_config():
    return CenturyConfig(
        agent_type_name="mock_guardrail",
        min_legionaries=1,
        max_legionaries=5,
        autoscale=False,
        task_timeout=10.0,
    )


@pytest.fixture
def century(century_config, agent_type, scheduler, event_bus):
    return Century(
        century_id="test-century",
        config=century_config,
        agent_type=agent_type,
        scheduler=scheduler,
        event_bus=event_bus,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_pressure(level: MemoryPressureLevel):
    """Return a context manager that forces _memory_pressure_level to return *level*."""
    return patch.object(
        CenturionScheduler,
        "_memory_pressure_level",
        return_value=level,
    )


def _patch_system_calls():
    """Patch all subprocess / OS calls that the scheduler makes so no real
    system resources are queried."""
    return [
        patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384),
        patch.object(CenturionScheduler, "_ram_available_mb", return_value=8192),
        patch("os.cpu_count", return_value=8),
        patch("os.getloadavg", return_value=(1.0, 1.0, 1.0)),
    ]


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_normal_state_allows_scheduling(scheduler, agent_type, throttle, event_bus):
    """Under NORMAL pressure agents can be scheduled and throttle reports NORMAL."""

    patches = _patch_system_calls() + [_patch_pressure(MemoryPressureLevel.NORMAL)]
    for p in patches:
        p.start()

    try:
        assert scheduler.can_schedule(agent_type) is True
        assert scheduler.available_slots(agent_type) > 0

        result = await throttle.check()
        assert result == MemoryPressureLevel.NORMAL
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_warn_blocks_scheduling_and_emits_caution(
    scheduler, agent_type, throttle, event_bus,
):
    """WARN pressure blocks admission and throttle emits memory_caution."""

    queue = event_bus.subscribe()
    patches = _patch_system_calls() + [_patch_pressure(MemoryPressureLevel.WARN)]
    for p in patches:
        p.start()

    try:
        # Scheduler must reject new agents.
        assert scheduler.can_schedule(agent_type) is False
        assert scheduler.available_slots(agent_type) == 0

        # Throttle should emit a caution or warning event.
        result = await throttle.check()
        assert result == MemoryPressureLevel.WARN

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        event_types = [e.event_type for e in events]
        assert any(
            et in ("memory_caution", "memory_warning") for et in event_types
        ), f"Expected memory_caution or memory_warning, got {event_types}"
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_warn_scale_down_terminates_idle_above_min(
    century, scheduler, agent_type,
):
    """At WARN pressure, _memory_pressure_scale_down removes idle agents above min."""

    patches = _patch_system_calls() + [_patch_pressure(MemoryPressureLevel.NORMAL)]
    for p in patches:
        p.start()

    try:
        # Spawn 3 legionaries under normal conditions.
        await century.muster(count=3)
        assert len(century.legionaries) == 3

        # Mark all legionaries IDLE (they should be by default after spawn).
        for leg in century.legionaries.values():
            leg.status = LegionaryStatus.IDLE
    finally:
        for p in patches:
            p.stop()

    # Now switch to WARN pressure and run scale-down.
    patches_warn = _patch_system_calls() + [_patch_pressure(MemoryPressureLevel.WARN)]
    for p in patches_warn:
        p.start()

    try:
        await century._memory_pressure_scale_down()
        # min_legionaries = 1, so excess = 3 - 1 = 2, should terminate 2 idle.
        assert len(century.legionaries) == 1
    finally:
        for p in patches_warn:
            p.stop()


@pytest.mark.asyncio
async def test_critical_blocks_scheduling_emits_critical_and_purges(
    scheduler, agent_type, throttle, event_bus,
):
    """CRITICAL pressure blocks admission, emits memory_critical, and attempts purge."""

    queue = event_bus.subscribe()
    patches = _patch_system_calls() + [_patch_pressure(MemoryPressureLevel.CRITICAL)]
    for p in patches:
        p.start()

    try:
        assert scheduler.can_schedule(agent_type) is False
        assert scheduler.available_slots(agent_type) == 0

        # Patch _attempt_purge so no real subprocess runs.
        with patch.object(throttle, "_attempt_purge") as mock_purge:
            result = await throttle.check()
            assert result == MemoryPressureLevel.CRITICAL
            mock_purge.assert_called_once()

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        event_types = [e.event_type for e in events]
        assert "memory_critical" in event_types, (
            f"Expected memory_critical, got {event_types}"
        )
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_critical_scale_down_terminates_all_idle(
    century, scheduler, agent_type,
):
    """At CRITICAL pressure, _memory_pressure_scale_down terminates ALL idle agents,
    even below min_legionaries."""

    patches = _patch_system_calls() + [_patch_pressure(MemoryPressureLevel.NORMAL)]
    for p in patches:
        p.start()

    try:
        await century.muster(count=3)
        assert len(century.legionaries) == 3
        for leg in century.legionaries.values():
            leg.status = LegionaryStatus.IDLE
    finally:
        for p in patches:
            p.stop()

    patches_crit = _patch_system_calls() + [_patch_pressure(MemoryPressureLevel.CRITICAL)]
    for p in patches_crit:
        p.start()

    try:
        await century._memory_pressure_scale_down()
        # CRITICAL removes ALL idle — even below min_legionaries.
        assert len(century.legionaries) == 0
    finally:
        for p in patches_crit:
            p.stop()


@pytest.mark.asyncio
async def test_return_to_normal_allows_scheduling_after_cooldown(
    scheduler, agent_type, throttle,
):
    """After pressure returns to NORMAL, scheduling is allowed again."""

    # First: enter CRITICAL state.
    patches_crit = _patch_system_calls() + [_patch_pressure(MemoryPressureLevel.CRITICAL)]
    for p in patches_crit:
        p.start()

    try:
        assert scheduler.can_schedule(agent_type) is False
        assert scheduler.available_slots(agent_type) == 0
    finally:
        for p in patches_crit:
            p.stop()

    # Then: return to NORMAL.
    patches_normal = _patch_system_calls() + [_patch_pressure(MemoryPressureLevel.NORMAL)]
    for p in patches_normal:
        p.start()

    try:
        # Force a fresh probe (bypass cache).
        scheduler._probe_cache = None

        assert scheduler.can_schedule(agent_type) is True
        assert scheduler.available_slots(agent_type) > 0

        result = await throttle.check()
        assert result == MemoryPressureLevel.NORMAL
    finally:
        for p in patches_normal:
            p.stop()


@pytest.mark.asyncio
async def test_full_pressure_cycle(
    scheduler, agent_type, throttle, event_bus, century,
):
    """End-to-end: NORMAL -> WARN -> CRITICAL -> NORMAL with all components."""

    queue = event_bus.subscribe()

    # ---- Phase 1: NORMAL ----
    patches = _patch_system_calls() + [_patch_pressure(MemoryPressureLevel.NORMAL)]
    for p in patches:
        p.start()
    try:
        assert scheduler.can_schedule(agent_type) is True
        slots = scheduler.available_slots(agent_type)
        assert slots > 0

        result = await throttle.check()
        assert result == MemoryPressureLevel.NORMAL

        # Spawn legionaries.
        await century.muster(count=3)
        assert len(century.legionaries) == 3
        for leg in century.legionaries.values():
            leg.status = LegionaryStatus.IDLE
    finally:
        for p in patches:
            p.stop()

    # ---- Phase 2: WARN ----
    patches = _patch_system_calls() + [_patch_pressure(MemoryPressureLevel.WARN)]
    for p in patches:
        p.start()
    try:
        assert scheduler.can_schedule(agent_type) is False
        assert scheduler.available_slots(agent_type) == 0

        result = await throttle.check()
        assert result == MemoryPressureLevel.WARN

        # Century scale-down removes idle above min.
        await century._memory_pressure_scale_down()
        assert len(century.legionaries) == 1
    finally:
        for p in patches:
            p.stop()

    # ---- Phase 3: CRITICAL ----
    # Mark remaining legionary idle for critical scale-down.
    for leg in century.legionaries.values():
        leg.status = LegionaryStatus.IDLE

    patches = _patch_system_calls() + [_patch_pressure(MemoryPressureLevel.CRITICAL)]
    for p in patches:
        p.start()
    try:
        assert scheduler.can_schedule(agent_type) is False
        assert scheduler.available_slots(agent_type) == 0

        with patch.object(throttle, "_attempt_purge") as mock_purge:
            result = await throttle.check()
            assert result == MemoryPressureLevel.CRITICAL
            mock_purge.assert_called_once()

        # Century terminates ALL idle.
        await century._memory_pressure_scale_down()
        assert len(century.legionaries) == 0
    finally:
        for p in patches:
            p.stop()

    # ---- Phase 4: NORMAL (recovery) ----
    patches = _patch_system_calls() + [_patch_pressure(MemoryPressureLevel.NORMAL)]
    for p in patches:
        p.start()
    try:
        scheduler._probe_cache = None

        assert scheduler.can_schedule(agent_type) is True
        assert scheduler.available_slots(agent_type) > 0

        result = await throttle.check()
        assert result == MemoryPressureLevel.NORMAL
    finally:
        for p in patches:
            p.stop()

    # Verify events were captured across the cycle.
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    event_types = [e.event_type for e in events]

    # Should have spawning, scale-down, and critical events.
    assert "legionary_spawned" in event_types
    assert "memory_scale_down" in event_types
    assert "memory_critical" in event_types
