"""Tests for CenturionScheduler — resource tracking and admission control."""

import pytest

from centurion.config import CenturionConfig
from centurion.core.scheduler import CenturionScheduler

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
