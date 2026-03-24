"""Tests for the AgentTypeRegistry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from centurion.agent_types.base import AgentResult, AgentType
from centurion.agent_types.registry import AgentTypeRegistry
from centurion.config import ResourceRequirements

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class FakeAgentType(AgentType):
    """Minimal concrete AgentType for testing the registry."""

    name = "fake"

    async def spawn(self, legionary_id: str, cwd: str, env: dict[str, str]) -> Any:
        return {"pid": 42}

    async def send_task(self, handle: Any, task: str, timeout: float) -> AgentResult:
        return AgentResult(success=True, output="done")

    async def stream_output(self, handle: Any) -> AsyncIterator[str]:
        yield "chunk"

    async def terminate(self, handle: Any, graceful: bool = True) -> None:
        pass

    def resource_requirements(self) -> ResourceRequirements:
        return ResourceRequirements()


class AnotherFakeAgentType(FakeAgentType):
    name = "another-fake"


def test_register_and_create():
    """Register a type, create an instance, and verify it is the correct class."""
    registry = AgentTypeRegistry()
    registry.register("fake", FakeAgentType)

    instance = registry.create("fake")
    assert isinstance(instance, FakeAgentType)
    assert instance.name == "fake"


def test_list_types():
    """Register multiple types and verify list_types() returns all of them."""
    registry = AgentTypeRegistry()
    registry.register("fake", FakeAgentType)
    registry.register("another", AnotherFakeAgentType)

    types = registry.list_types()
    assert len(types) == 2
    assert "fake" in types
    assert "another" in types
    assert types["fake"] is FakeAgentType
    assert types["another"] is AnotherFakeAgentType


def test_unknown_type_raises():
    """Creating an unregistered type should raise ValueError with a helpful message."""
    registry = AgentTypeRegistry()
    registry.register("fake", FakeAgentType)

    with pytest.raises(ValueError, match="Unknown agent type 'nonexistent'"):
        registry.create("nonexistent")


def test_list_types_returns_copy():
    """list_types() returns a copy, so mutating it does not affect the registry."""
    registry = AgentTypeRegistry()
    registry.register("fake", FakeAgentType)

    types = registry.list_types()
    types.clear()

    assert len(registry.list_types()) == 1
