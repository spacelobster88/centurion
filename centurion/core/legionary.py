"""Legionary — individual agent instance (equivalent to a K8s Pod)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from centurion.agent_types.base import AgentResult, AgentType


class LegionaryStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    FAILED = "failed"
    TERMINATED = "terminated"


MAX_CONSECUTIVE_FAILURES = 3


@dataclass
class Legionary:
    """A single agent instance within a Century."""

    id: str = field(default_factory=lambda: f"leg-{uuid.uuid4().hex[:8]}")
    century_id: str = ""
    agent_type: AgentType | None = None
    status: LegionaryStatus = LegionaryStatus.IDLE
    cwd: str = ""
    handle: Any = None
    current_task_id: str | None = None
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_duration: float = 0.0
    consecutive_failures: int = 0

    @property
    def needs_replacement(self) -> bool:
        return self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES

    async def execute(self, task_id: str, prompt: str, timeout: float) -> AgentResult:
        """Execute a task on this legionary. Updates internal counters."""
        if self.agent_type is None:
            raise RuntimeError(f"Legionary {self.id} has no agent_type assigned")

        self.status = LegionaryStatus.BUSY
        self.current_task_id = task_id
        try:
            result = await self.agent_type.send_task(self.handle, prompt, timeout)
            result.legionary_id = self.id
            result.task_id = task_id
            if result.success:
                self.tasks_completed += 1
                self.consecutive_failures = 0
            else:
                self.tasks_failed += 1
                self.consecutive_failures += 1
            self.total_duration += result.duration_seconds
            return result
        except Exception as e:
            self.tasks_failed += 1
            self.consecutive_failures += 1
            self.status = LegionaryStatus.FAILED
            return AgentResult(
                legionary_id=self.id,
                task_id=task_id,
                success=False,
                error=str(e),
            )
        finally:
            self.last_active = time.time()
            if self.status != LegionaryStatus.FAILED:
                self.status = LegionaryStatus.IDLE
            self.current_task_id = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "century_id": self.century_id,
            "agent_type": self.agent_type.name if self.agent_type else None,
            "status": self.status.value,
            "current_task_id": self.current_task_id,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "total_duration": round(self.total_duration, 2),
            "consecutive_failures": self.consecutive_failures,
        }
