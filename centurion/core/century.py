"""Century — a squad of same-type agents with a shared task queue.

Equivalent to a K8s ReplicaSet + HorizontalPodAutoscaler.
The autoscaler loop is called the Optio (second-in-command).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from centurion.agent_types.base import AgentResult, AgentType
from centurion.core.circuit_breaker import CircuitBreaker
from centurion.core.exceptions import (
    AgentAPIError,
    AgentProcessError,
    CenturionError,
    TaskTimeoutError,
)
from centurion.core.legionary import Legionary, LegionaryStatus

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from centurion.core.events import EventBus
    from centurion.core.scheduler import CenturionScheduler


@dataclass
class CenturyConfig:
    """Configuration for a Century."""

    agent_type_name: str = "claude_cli"
    agent_type_config: dict = field(default_factory=dict)
    min_legionaries: int = 1
    max_legionaries: int = 10
    autoscale: bool = True
    task_timeout: float = 300.0
    scale_up_threshold: int = 2
    scale_down_delay: float = 60.0
    cooldown: float = 15.0
    cwd_base: str = "/tmp/centurion-sessions"


# Priority queue item: (priority, submission_time, task_id, prompt, future)
type QueueItem = tuple[int, float, str, str, asyncio.Future[AgentResult]]


class Century:
    """A squad of same-type agents consuming from a shared priority queue."""

    def __init__(
        self,
        century_id: str,
        config: CenturyConfig,
        agent_type: AgentType,
        scheduler: CenturionScheduler | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.id = century_id
        self.config = config
        self.agent_type = agent_type
        self.scheduler = scheduler
        self.event_bus = event_bus
        self.legionaries: dict[str, Legionary] = {}
        self.task_queue: asyncio.PriorityQueue[QueueItem] = asyncio.PriorityQueue(maxsize=1000)
        self._workers: dict[str, asyncio.Task] = {}
        self._optio_task: asyncio.Task | None = None
        self._circuit_breaker = CircuitBreaker(name=century_id)
        self._running = False
        self._last_scale_time: float = 0.0
        self._queue_empty_since: float | None = None
        self.created_at: float = time.time()

    async def muster(self, count: int | None = None) -> list[Legionary]:
        """Spawn legionaries. Returns the newly created ones."""
        target = count or self.config.min_legionaries
        created = []
        for _ in range(target):
            leg = await self._spawn_legionary()
            if leg:
                created.append(leg)
        return created

    async def start(self) -> None:
        """Start worker loops and the Optio autoscaler."""
        self._running = True
        for leg_id in list(self.legionaries):
            self._start_worker(leg_id)
        if self.config.autoscale:
            self._optio_task = asyncio.create_task(self._optio_loop())

    async def submit_task(
        self, prompt: str, priority: int = 5, task_id: str | None = None
    ) -> asyncio.Future[AgentResult]:
        """Submit a task to this century's queue. Returns a Future with the result."""
        task_id = task_id or f"task-{uuid.uuid4().hex[:8]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[AgentResult] = loop.create_future()
        try:
            self.task_queue.put_nowait((priority, time.time(), task_id, prompt, future))
        except asyncio.QueueFull:
            if not future.done():
                future.set_exception(CenturionError(f"Century {self.id} queue full (max 1000)", retryable=True))
            return future
        logger.info(
            "Task submitted",
            extra={"century_id": self.id, "task_id": task_id, "priority": priority, "queue_depth": self.task_queue.qsize()},
        )

        if self.event_bus:
            await self.event_bus.emit(
                "task_submitted",
                entity_type="task",
                entity_id=task_id,
                payload={"century_id": self.id, "priority": priority},
            )
        return future

    async def dismiss(self) -> None:
        """Terminate all legionaries and stop workers. Fails pending futures."""
        self._running = False
        if self._optio_task:
            self._optio_task.cancel()
            self._optio_task = None

        for worker in self._workers.values():
            worker.cancel()
        self._workers.clear()

        for leg in list(self.legionaries.values()):
            await self._terminate_legionary(leg)
        self.legionaries.clear()

        # Drain the queue and fail all pending futures
        drained = 0
        while not self.task_queue.empty():
            try:
                _, _, task_id, _, future = self.task_queue.get_nowait()
                if not future.done():
                    future.set_exception(
                        CenturionError(
                            f"Century {self.id} dismissed; task {task_id} cancelled",
                            retryable=False,
                        )
                    )
                self.task_queue.task_done()
                drained += 1
            except asyncio.QueueEmpty:
                break
        if drained:
            logger.info(
                "Century %s dismissed: failed %d pending futures", self.id, drained,
            )

    async def scale_to(self, target: int) -> None:
        """Scale legionaries to exact target count."""
        target = max(self.config.min_legionaries, min(target, self.config.max_legionaries))
        current = len(self.legionaries)
        if target > current:
            await self._scale_up(target - current)
        elif target < current:
            await self._scale_down(current - target)

    def status_report(self) -> dict:
        return {
            "century_id": self.id,
            "agent_type": self.agent_type.name,
            "config": {
                "min_legionaries": self.config.min_legionaries,
                "max_legionaries": self.config.max_legionaries,
                "autoscale": self.config.autoscale,
                "task_timeout": self.config.task_timeout,
            },
            "legionaries_count": len(self.legionaries),
            "idle": sum(1 for l in self.legionaries.values() if l.status == LegionaryStatus.IDLE),
            "busy": sum(1 for l in self.legionaries.values() if l.status == LegionaryStatus.BUSY),
            "failed": sum(1 for l in self.legionaries.values() if l.status == LegionaryStatus.FAILED),
            "queue_depth": self.task_queue.qsize(),
            "total_tasks_completed": sum(l.tasks_completed for l in self.legionaries.values()),
            "total_tasks_failed": sum(l.tasks_failed for l in self.legionaries.values()),
        }

    # --- Internal ---

    async def _spawn_legionary(self) -> Legionary | None:
        """Create and register a single legionary."""
        if self.scheduler and not self.scheduler.can_schedule(self.agent_type):
            if self.event_bus:
                await self.event_bus.emit(
                    "scheduler_rejected",
                    entity_type="century",
                    entity_id=self.id,
                    payload={"reason": "insufficient resources"},
                )
            return None

        leg = Legionary(
            century_id=self.id,
            agent_type=self.agent_type,
        )
        leg.cwd = os.path.join(self.config.cwd_base, leg.id)
        os.makedirs(leg.cwd, exist_ok=True)
        leg.handle = await self.agent_type.spawn(leg.id, leg.cwd, {})
        self.legionaries[leg.id] = leg

        if self.scheduler:
            self.scheduler.allocate(self.agent_type)
        if self.event_bus:
            await self.event_bus.emit(
                "legionary_spawned",
                entity_type="legionary",
                entity_id=leg.id,
                payload={"century_id": self.id},
            )
        return leg

    async def _terminate_legionary(self, leg: Legionary) -> None:
        """Terminate a legionary and free resources."""
        if leg.handle is not None:
            try:
                await self.agent_type.terminate(leg.handle)
            except Exception:
                pass
        leg.status = LegionaryStatus.TERMINATED

        if self.scheduler:
            self.scheduler.release(self.agent_type)
        if self.event_bus:
            await self.event_bus.emit(
                "legionary_terminated",
                entity_type="legionary",
                entity_id=leg.id,
                payload={"century_id": self.id},
            )

    def _start_worker(self, leg_id: str) -> None:
        task = asyncio.create_task(self._worker_loop(leg_id))
        self._workers[leg_id] = task

    async def _worker_loop(self, leg_id: str) -> None:
        """Consume tasks from the queue and execute on the assigned legionary."""
        while self._running:
            try:
                priority, _, task_id, prompt, future = await asyncio.wait_for(
                    self.task_queue.get(), timeout=5.0,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                if not self._running:
                    break
                continue

            leg = self.legionaries.get(leg_id)
            if not leg or leg.status == LegionaryStatus.TERMINATED:
                # Put task back if legionary is gone
                self.task_queue.task_done()
                if not future.done():
                    await self.task_queue.put((priority, time.time(), task_id, prompt, future))
                break

            # Circuit breaker check: if open, re-queue and wait
            if not self._circuit_breaker.can_execute():
                if not future.done():
                    await self.task_queue.put((priority, time.time(), task_id, prompt, future))
                self.task_queue.task_done()
                await asyncio.sleep(1.0)
                continue

            if self.event_bus:
                await self.event_bus.emit(
                    "task_started",
                    entity_type="task",
                    entity_id=task_id,
                    payload={"legionary_id": leg_id, "century_id": self.id},
                )

            try:
                result = await leg.execute(task_id, prompt, self.config.task_timeout)
                if not future.done():
                    future.set_result(result)

                if result.success:
                    self._circuit_breaker.record_success()
                    logger.info(
                        "Task completed",
                        extra={"task_id": task_id, "legionary_id": leg_id, "duration_s": result.duration_seconds, "success": True},
                    )
                else:
                    self._circuit_breaker.record_failure()
                    logger.warning(
                        "Task failed",
                        extra={"task_id": task_id, "legionary_id": leg_id, "duration_s": result.duration_seconds, "error": result.error},
                    )

                event_type = "task_completed" if result.success else "task_failed"
                if self.event_bus:
                    await self.event_bus.emit(
                        event_type,
                        entity_type="task",
                        entity_id=task_id,
                        payload={
                            "legionary_id": leg_id,
                            "success": result.success,
                            "duration": result.duration_seconds,
                        },
                    )
            except TaskTimeoutError as exc:
                self._circuit_breaker.record_failure()
                logger.warning(
                    "Task timed out",
                    extra={"task_id": task_id, "legionary_id": leg_id, "timeout_seconds": exc.timeout_seconds, "error_type": type(exc).__name__},
                )
                if not future.done():
                    future.set_exception(exc)
            except (AgentProcessError, AgentAPIError) as exc:
                self._circuit_breaker.record_failure()
                logger.error(
                    "Task execution exception",
                    extra={"task_id": task_id, "legionary_id": leg_id, "error_type": type(exc).__name__, "retryable": exc.retryable},
                    exc_info=True,
                )
                if not future.done():
                    future.set_exception(exc)
            except Exception as e:
                self._circuit_breaker.record_failure()
                logger.error(
                    "Task execution exception",
                    extra={"task_id": task_id, "legionary_id": leg_id, "error_type": type(e).__name__},
                    exc_info=True,
                )
                if not future.done():
                    future.set_exception(e)
            finally:
                self.task_queue.task_done()

            # Check if legionary needs replacement (liveness probe)
            if leg.needs_replacement:
                await self._replace_legionary(leg_id)
                break

    async def _replace_legionary(self, leg_id: str) -> None:
        """Replace a failed legionary with a fresh one."""
        old = self.legionaries.pop(leg_id, None)
        if old:
            await self._terminate_legionary(old)
        worker = self._workers.pop(leg_id, None)
        if worker:
            worker.cancel()

        new_leg = await self._spawn_legionary()
        if new_leg and self._running:
            self._start_worker(new_leg.id)
            if self.event_bus:
                await self.event_bus.emit(
                    "legionary_replaced",
                    entity_type="legionary",
                    entity_id=new_leg.id,
                    payload={"replaced": leg_id, "century_id": self.id},
                )

    async def _scale_up(self, count: int) -> None:
        for _ in range(count):
            leg = await self._spawn_legionary()
            if leg and self._running:
                self._start_worker(leg.id)
        self._last_scale_time = time.time()
        if self.event_bus:
            await self.event_bus.emit(
                "century_scaled_up",
                entity_type="century",
                entity_id=self.id,
                payload={"added": count, "total": len(self.legionaries)},
            )

    async def _scale_down(self, count: int) -> None:
        idle = [
            lid for lid, l in self.legionaries.items()
            if l.status == LegionaryStatus.IDLE
        ]
        to_remove = idle[:count]
        for lid in to_remove:
            leg = self.legionaries.pop(lid, None)
            if leg:
                await self._terminate_legionary(leg)
            worker = self._workers.pop(lid, None)
            if worker:
                worker.cancel()
        self._last_scale_time = time.time()
        if self.event_bus:
            await self.event_bus.emit(
                "century_scaled_down",
                entity_type="century",
                entity_id=self.id,
                payload={"removed": len(to_remove), "total": len(self.legionaries)},
            )

    async def _optio_loop(self) -> None:
        """Autoscaler loop — the Optio. Must never crash."""
        consecutive_errors = 0
        max_consecutive = 5

        while self._running:
            try:
                await asyncio.sleep(self.config.cooldown)
                if not self._running:
                    break
                await self._optio_check()
                consecutive_errors = 0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                consecutive_errors += 1
                logger.exception(
                    "Optio %s: unexpected error (%d/%d): %s",
                    self.id, consecutive_errors, max_consecutive, exc,
                )

            if consecutive_errors >= max_consecutive:
                logger.critical(
                    "Optio %s: %d consecutive errors, backing off 60s",
                    self.id, consecutive_errors,
                )
                await asyncio.sleep(60.0)
                consecutive_errors = 0

    async def _optio_check(self) -> None:
        """Single autoscale evaluation."""
        if time.time() - self._last_scale_time < self.config.cooldown:
            return

        queue_depth = self.task_queue.qsize()
        idle_count = sum(1 for l in self.legionaries.values() if l.status == LegionaryStatus.IDLE)
        current = len(self.legionaries)

        # Scale up
        if queue_depth > idle_count * self.config.scale_up_threshold and current < self.config.max_legionaries:
            needed = min(
                queue_depth - idle_count,
                self.config.max_legionaries - current,
            )
            if self.scheduler:
                needed = min(needed, self.scheduler.available_slots(self.agent_type))
            if needed > 0:
                logger.info(
                    "Optio: scaling up",
                    extra={"century_id": self.id, "queue_depth": queue_depth, "current_agents": current, "adding": needed},
                )
                await self._scale_up(needed)
            return

        # Scale down
        if queue_depth == 0:
            if self._queue_empty_since is None:
                self._queue_empty_since = time.time()
            elif (
                time.time() - self._queue_empty_since > self.config.scale_down_delay
                and idle_count > 1
                and current > self.config.min_legionaries
            ):
                excess = min(idle_count - 1, current - self.config.min_legionaries)
                if excess > 0:
                    logger.info(
                        "Optio: scaling down",
                        extra={"century_id": self.id, "queue_depth": queue_depth, "current_agents": current, "removing": excess},
                    )
                    await self._scale_down(excess)
                self._queue_empty_since = None
        else:
            self._queue_empty_since = None
