"""Legionary — individual agent instance (equivalent to a K8s Pod)."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from centurion.core.exceptions import AgentProcessError, TaskTimeoutError

if TYPE_CHECKING:
    from centurion.agent_types.base import AgentResult, AgentType

logger = logging.getLogger(__name__)


class LegionaryStatus(StrEnum):
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
    broadcasts: list[dict] = field(default_factory=list)

    @property
    def needs_replacement(self) -> bool:
        return self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES

    async def execute(self, task_id: str, prompt: str, timeout: float) -> AgentResult:
        """Execute a task on this legionary. Updates internal counters."""
        if self.agent_type is None:
            raise RuntimeError(f"Legionary {self.id} has no agent_type assigned")

        self.status = LegionaryStatus.BUSY
        self.current_task_id = task_id
        start_time = time.monotonic()
        logger.debug("Task started", extra={"legionary_id": self.id, "task_id": task_id})
        try:
            result = await self.agent_type.send_task(self.handle, prompt, timeout)
            result.legionary_id = self.id
            result.task_id = task_id
            duration = time.monotonic() - start_time
            if result.success:
                self.tasks_completed += 1
                self.consecutive_failures = 0
                logger.info(
                    "Task completed",
                    extra={
                        "legionary_id": self.id,
                        "task_id": task_id,
                        "duration_s": round(duration, 3),
                        "success": True,
                    },
                )
            else:
                self.tasks_failed += 1
                self.consecutive_failures += 1
                logger.warning(
                    "Task failed",
                    extra={
                        "legionary_id": self.id,
                        "task_id": task_id,
                        "duration_s": round(duration, 3),
                        "error": result.error,
                    },
                )
                # Classify non-success results into typed exceptions
                if result.exit_code is not None and result.exit_code != 0:
                    crash_codes = {-9, -15, 137, 139}
                    if result.exit_code in crash_codes:
                        raise AgentProcessError(
                            result.error or f"Process exited {result.exit_code}",
                            exit_code=result.exit_code,
                            stderr=result.error or "",
                        )
            self.total_duration += result.duration_seconds
            return result
        except TimeoutError as exc:
            duration = time.monotonic() - start_time
            self.tasks_failed += 1
            self.consecutive_failures += 1
            logger.warning(
                "Task timed out",
                extra={
                    "legionary_id": self.id,
                    "task_id": task_id,
                    "duration_s": round(duration, 3),
                    "timeout": timeout,
                },
            )
            raise TaskTimeoutError(
                f"Task {task_id} timed out after {timeout}s",
                timeout_seconds=timeout,
            ) from exc
        except TaskTimeoutError:
            self.tasks_failed += 1
            self.consecutive_failures += 1
            # Timeout is transient -- legionary is still usable, do NOT set FAILED
            raise
        except AgentProcessError as exc:
            self.tasks_failed += 1
            self.consecutive_failures += 1
            if not exc.retryable:
                self.status = LegionaryStatus.FAILED
            logger.warning(
                "Task execution exception",
                extra={
                    "legionary_id": self.id,
                    "task_id": task_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            raise
        except Exception as e:
            duration = time.monotonic() - start_time
            self.tasks_failed += 1
            self.consecutive_failures += 1
            self.status = LegionaryStatus.FAILED
            logger.warning(
                "Task execution exception",
                extra={
                    "legionary_id": self.id,
                    "task_id": task_id,
                    "duration_s": round(duration, 3),
                    "error_type": type(e).__name__,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise AgentProcessError(
                f"Unexpected error in legionary {self.id}: {e}",
                exit_code=None,
            ) from e
        finally:
            self.last_active = time.time()
            if self.status != LegionaryStatus.FAILED:
                self.status = LegionaryStatus.IDLE
            self.current_task_id = None

    async def receive_broadcast(self, message: str) -> None:
        """Receive a broadcast message. Stores in message inbox."""
        self.broadcasts.append(
            {
                "message": message,
                "received_at": time.time(),
            }
        )
        logger.debug(
            "Broadcast received",
            extra={"legionary_id": self.id, "message_len": len(message)},
        )

    def to_dict(self, session_registry: Any | None = None) -> dict:
        result = {
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
        if session_registry is not None:
            info = session_registry.closeable_info(self.id)
            result["has_bg_children"] = info["has_bg_children"]
            result["bg_child_ids"] = info["bg_child_ids"]
            result["closeable"] = info["closeable"]
        return result
