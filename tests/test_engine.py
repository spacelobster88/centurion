"""Tests for the Centurion engine — top-level orchestrator."""

import pytest

from centurion.core.century import CenturyConfig
from centurion.core.engine import Centurion
from centurion.config import CenturionConfig

from tests.conftest import MockAgentType


@pytest.fixture
def engine():
    """Create a Centurion engine with the mock agent type registered."""
    eng = Centurion(config=CenturionConfig())
    eng.registry.register("mock", MockAgentType)
    return eng


async def test_raise_and_disband_legion(engine):
    """Full lifecycle: raise a legion, verify it exists, disband it."""
    legion = await engine.raise_legion("test-legion", name="Test Legion")

    assert "test-legion" in engine.legions
    assert legion.id == "test-legion"
    assert legion.name == "Test Legion"

    await engine.disband_legion("test-legion")

    assert "test-legion" not in engine.legions


async def test_fleet_status(engine):
    """Fleet status contains the expected top-level structure."""
    await engine.raise_legion("status-legion", name="Status Legion")

    status = engine.fleet_status()

    assert "total_legions" in status
    assert "total_centuries" in status
    assert "total_legionaries" in status
    assert "legions" in status
    assert "hardware" in status
    assert status["total_legions"] == 1
    assert "status-legion" in status["legions"]

    # Hardware section should have system info
    hw = status["hardware"]
    assert "system" in hw
    assert "allocated" in hw
    assert "recommended_max_agents" in hw

    await engine.disband_legion("status-legion")


async def test_duplicate_legion_raises(engine):
    """Raising a legion with a duplicate ID raises ValueError."""
    await engine.raise_legion("dup-legion", name="First")

    with pytest.raises(ValueError, match="already exists"):
        await engine.raise_legion("dup-legion", name="Second")

    await engine.disband_legion("dup-legion")


async def test_shutdown(engine):
    """Shutdown terminates all legions and leaves the engine empty."""
    legion = await engine.raise_legion("shutdown-legion", name="Shutdown Test")

    # Pass scheduler=None to bypass resource admission control in tests,
    # since the mock agent does not require real system resources.
    await legion.add_century(
        "cent-shutdown",
        CenturyConfig(agent_type_name="mock", min_legionaries=2, autoscale=False),
        engine.registry,
        None,
        engine.event_bus,
    )

    assert engine.fleet_status()["total_legionaries"] == 2

    await engine.shutdown()

    assert len(engine.legions) == 0
