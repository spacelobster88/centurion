"""Tests for Legion -- deployment group with quota enforcement."""

import asyncio

import pytest

from centurion.agent_types.registry import AgentTypeRegistry
from centurion.core.century import Century, CenturyConfig
from centurion.core.legion import Legion, LegionQuota

from tests.conftest import MockAgentType


@pytest.fixture
def mock_registry():
    """Registry with only the mock agent type registered."""
    registry = AgentTypeRegistry()
    registry.register("mock", MockAgentType)
    return registry


async def test_add_century(mock_registry):
    """Adding a century registers it in the legion."""
    legion = Legion(legion_id="legion-add", name="Test Legion")

    century = await legion.add_century(
        "cent-alpha",
        CenturyConfig(agent_type_name="mock", min_legionaries=2, autoscale=False),
        mock_registry,
    )

    assert "cent-alpha" in legion.centuries
    assert legion.centuries["cent-alpha"] is century
    assert len(century.legionaries) == 2

    await legion.dismiss_all()


async def test_submit_batch_round_robin(mock_registry):
    """Batch submission distributes tasks round-robin across centuries."""
    legion = Legion(legion_id="legion-rr", name="Round Robin Legion")

    cent_a = await legion.add_century(
        "cent-a",
        CenturyConfig(agent_type_name="mock", min_legionaries=1, autoscale=False),
        mock_registry,
    )
    cent_b = await legion.add_century(
        "cent-b",
        CenturyConfig(agent_type_name="mock", min_legionaries=1, autoscale=False),
        mock_registry,
    )

    prompts = ["Task 1", "Task 2", "Task 3", "Task 4"]
    futures = await legion.submit_batch(prompts, priority=5, distribute="round_robin")

    assert len(futures) == 4

    # Wait for all results
    results = await asyncio.wait_for(
        asyncio.gather(*futures),
        timeout=10.0,
    )
    assert all(r.success for r in results)
    assert len(results) == 4

    await legion.dismiss_all()


async def test_quota_enforcement(mock_registry):
    """Exceeding max_centuries quota raises ValueError."""
    quota = LegionQuota(max_centuries=1, max_legionaries=100)
    legion = Legion(legion_id="legion-quota", name="Quota Legion", quota=quota)

    await legion.add_century(
        "cent-first",
        CenturyConfig(agent_type_name="mock", min_legionaries=1, autoscale=False),
        mock_registry,
    )

    with pytest.raises(ValueError, match="quota exceeded"):
        await legion.add_century(
            "cent-second",
            CenturyConfig(agent_type_name="mock", min_legionaries=1, autoscale=False),
            mock_registry,
        )

    await legion.dismiss_all()


async def test_dismiss_all(mock_registry):
    """Dismissing all centuries empties the legion."""
    legion = Legion(legion_id="legion-dismiss", name="Dismiss Legion")

    await legion.add_century(
        "cent-1",
        CenturyConfig(agent_type_name="mock", min_legionaries=2, autoscale=False),
        mock_registry,
    )
    await legion.add_century(
        "cent-2",
        CenturyConfig(agent_type_name="mock", min_legionaries=2, autoscale=False),
        mock_registry,
    )

    assert len(legion.centuries) == 2
    assert legion.total_legionaries == 4

    await legion.dismiss_all()

    assert len(legion.centuries) == 0
    assert legion.total_legionaries == 0
