"""Agent type registry — maps type names to AgentType implementations."""

from __future__ import annotations

from typing import Any

from centurion.agent_types.base import AgentType


class AgentTypeRegistry:
    """Registry of available agent type plugins."""

    def __init__(self) -> None:
        self._types: dict[str, type[AgentType]] = {}

    def register(self, name: str, cls: type[AgentType]) -> None:
        """Register an agent type class under a name."""
        self._types[name] = cls

    def create(self, name: str, **kwargs: Any) -> AgentType:
        """Instantiate a registered agent type by name."""
        cls = self._types.get(name)
        if cls is None:
            available = ", ".join(sorted(self._types)) or "(none)"
            raise ValueError(f"Unknown agent type {name!r}. Available: {available}")
        return cls(**kwargs)

    def list_types(self) -> dict[str, type[AgentType]]:
        """Return all registered type name → class mappings."""
        return dict(self._types)
