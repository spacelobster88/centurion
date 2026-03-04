"""Tests for CenturionScheduler — resource tracking and admission control."""

import time
from unittest.mock import patch

import pytest

from centurion.config import CenturionConfig
from centurion.core.scheduler import CenturionScheduler, SystemResources

from tests.conftest import MockAgentType


@pytest.fixture
def scheduler():
    """Create a scheduler with default config."""
    return CenturionScheduler(config=CenturionConfig())


@pytest.fixture
def mock_agent():
    """A mock agent type with minimal resource requirements (10m CPU, 10 MB RAM)."""
    return MockAgentType()


async def test_probe_system(scheduler):
    """System probe detects valid CPU count and RAM values."""
    resources = scheduler.probe_system()

    assert resources.cpu_count > 0
    assert resources.ram_total_mb > 0
    assert resources.ram_available_mb > 0
    assert resources.load_avg_1 >= 0
    assert resources.load_avg_5 >= 0
    assert resources.load_avg_15 >= 0


async def test_recommended_max(scheduler):
    """Recommended max agents is a positive number on any real machine."""
    recommended = scheduler.recommended_max_agents()

    assert recommended > 0


async def test_allocate_release(scheduler, mock_agent):
    """Allocating resources increments counters; releasing restores them."""
    assert scheduler.active_agents == 0
    assert scheduler.allocated_cpu == 0
    assert scheduler.allocated_memory == 0

    scheduler.allocate(mock_agent)

    assert scheduler.active_agents == 1
    assert scheduler.allocated_cpu == 10  # MockAgentType requests 10 millicores
    assert scheduler.allocated_memory == 10  # MockAgentType requests 10 MB

    scheduler.allocate(mock_agent)

    assert scheduler.active_agents == 2
    assert scheduler.allocated_cpu == 20
    assert scheduler.allocated_memory == 20

    scheduler.release(mock_agent)

    assert scheduler.active_agents == 1
    assert scheduler.allocated_cpu == 10
    assert scheduler.allocated_memory == 10

    scheduler.release(mock_agent)

    assert scheduler.active_agents == 0
    assert scheduler.allocated_cpu == 0
    assert scheduler.allocated_memory == 0


async def test_can_schedule(mock_agent):
    """After allocating until full, can_schedule returns False."""
    # Use zero RAM headroom so the memory check passes on any machine,
    # and a hard limit to make the test deterministic.
    config = CenturionConfig()
    config.ram_headroom_gb = 0.0
    config.max_agents_hard_limit = 3
    sched = CenturionScheduler(config=config)

    assert sched.can_schedule(mock_agent) is True

    sched.allocate(mock_agent)
    sched.allocate(mock_agent)
    sched.allocate(mock_agent)

    # Hard limit of 3 reached
    assert sched.active_agents == 3
    assert sched.can_schedule(mock_agent) is False

    # Release one and verify scheduling is possible again
    sched.release(mock_agent)
    assert sched.can_schedule(mock_agent) is True


# ---------------------------------------------------------------------------
# Probe cache TTL tests (S9 fix)
# ---------------------------------------------------------------------------

class TestProbeCacheTTL:
    def test_probe_system_returns_system_resources(self, scheduler):
        """probe_system returns a SystemResources dataclass."""
        result = scheduler.probe_system()
        assert isinstance(result, SystemResources)
        assert result.cpu_count > 0
        assert result.ram_total_mb > 0

    def test_probe_system_uses_cache_within_ttl(self, scheduler):
        """Within the 5s TTL, probe_system returns the cached object (same id)."""
        first = scheduler.probe_system()
        second = scheduler.probe_system()
        # Same object means cache was used, no re-probe
        assert first is second

    def test_probe_system_refreshes_after_ttl(self, scheduler):
        """After the 5s TTL expires, probe_system fetches fresh data."""
        first = scheduler.probe_system()
        # Simulate time passing beyond the 5s TTL by backdating the cache timestamp
        scheduler._probe_cache_time = time.monotonic() - 6.0
        second = scheduler.probe_system()
        # A new object should have been created (different identity)
        assert first is not second
        assert isinstance(second, SystemResources)

    def test_probe_cache_respects_exact_boundary(self, scheduler):
        """Cache is still valid at exactly 4.9s but stale at 5.1s."""
        first = scheduler.probe_system()

        # Still within TTL at 4.9s
        scheduler._probe_cache_time = time.monotonic() - 4.9
        within_ttl = scheduler.probe_system()
        assert first is within_ttl

        # Beyond TTL at 5.1s
        scheduler._probe_cache_time = time.monotonic() - 5.1
        beyond_ttl = scheduler.probe_system()
        assert first is not beyond_ttl


# ---------------------------------------------------------------------------
# can_schedule respects hard limits
# ---------------------------------------------------------------------------

class TestCanScheduleHardLimits:
    def test_can_schedule_respects_hard_limit_zero_means_unlimited(self):
        """When max_agents_hard_limit is 0, scheduling is not capped by it."""
        config = CenturionConfig()
        config.max_agents_hard_limit = 0
        config.ram_headroom_gb = 0.0
        sched = CenturionScheduler(config=config)
        agent = MockAgentType()
        # Should be able to schedule with hard limit disabled
        assert sched.can_schedule(agent) is True

    def test_can_schedule_blocks_at_hard_limit(self):
        """When active_agents reaches hard limit, can_schedule returns False."""
        config = CenturionConfig()
        config.max_agents_hard_limit = 2
        config.ram_headroom_gb = 0.0
        sched = CenturionScheduler(config=config)
        agent = MockAgentType()

        sched.allocate(agent)
        sched.allocate(agent)
        assert sched.active_agents == 2
        assert sched.can_schedule(agent) is False


# ---------------------------------------------------------------------------
# available_slots calculation
# ---------------------------------------------------------------------------

class TestAvailableSlots:
    def test_available_slots_with_hard_limit(self):
        """available_slots accounts for the hard limit cap."""
        config = CenturionConfig()
        config.max_agents_hard_limit = 5
        config.ram_headroom_gb = 0.0
        sched = CenturionScheduler(config=config)
        agent = MockAgentType()

        slots_before = sched.available_slots(agent)
        # Hard limit is 5 with 0 active, so hard_slots = 5
        # slots should be min(cpu_slots, mem_slots, hard_slots) and >= 0
        assert slots_before >= 0
        assert slots_before <= 5  # cannot exceed hard limit

        sched.allocate(agent)
        sched.allocate(agent)
        slots_after = sched.available_slots(agent)
        # Used 2, so hard_slots = 3; slots decreased
        assert slots_after <= slots_before
        assert slots_after <= 3

    def test_available_slots_never_negative(self):
        """available_slots returns 0, never a negative number."""
        config = CenturionConfig()
        config.max_agents_hard_limit = 1
        config.ram_headroom_gb = 0.0
        sched = CenturionScheduler(config=config)
        agent = MockAgentType()

        sched.allocate(agent)
        sched.allocate(agent)  # over-allocate beyond hard limit
        slots = sched.available_slots(agent)
        assert slots >= 0
