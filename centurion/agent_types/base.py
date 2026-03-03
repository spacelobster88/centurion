"""Agent type abstraction — strategy/plugin pattern for different AI backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from centurion.config import ResourceRequirements


@dataclass
class AgentResult:
    """Standardized result from any agent type."""

    legionary_id: str = ""
    task_id: str = ""
    success: bool = False
    output: str = ""
    error: str | None = None
    exit_code: int | None = None
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentType(ABC):
    """Abstract base class for agent backends.

    Each concrete type (Claude CLI, Claude API, Shell) implements this
    interface. Registered in AgentTypeRegistry and used by Century to
    manage legionaries of a given type.
    """

    name: str = "base"

    @abstractmethod
    async def spawn(self, legionary_id: str, cwd: str, env: dict[str, str]) -> Any:
        """Create the underlying process/connection. Returns an opaque handle."""
        ...

    @abstractmethod
    async def send_task(self, handle: Any, task: str, timeout: float) -> AgentResult:
        """Execute a task and wait for completion."""
        ...

    @abstractmethod
    async def stream_output(self, handle: Any) -> AsyncIterator[str]:
        """Yield incremental output chunks for real-time streaming."""
        ...

    @abstractmethod
    async def terminate(self, handle: Any, graceful: bool = True) -> None:
        """Kill the agent process/connection."""
        ...

    @abstractmethod
    def resource_requirements(self) -> ResourceRequirements:
        """Declare resource needs for K8s-inspired scheduling."""
        ...
