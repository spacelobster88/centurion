"""Centurion — the orchestrator engine (Control Plane).

Singleton per process. Manages legions, scheduling, and the event bus.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from centurion.agent_types.registry import AgentTypeRegistry
from centurion.config import CenturionConfig
from centurion.core.broadcast import Broadcaster
from centurion.core.events import EventBus
from centurion.core.legion import Legion, LegionQuota
from centurion.core.scheduler import CenturionScheduler
from centurion.core.sentinel import Sentinel, SentinelConfig
from centurion.core.session_registry import SessionRegistry

logger = logging.getLogger(__name__)


class Centurion:
    """The Centurion engine — commands all legions.

    Usage::

        engine = Centurion()
        legion = await engine.raise_legion("alpha", name="Research Team")
        century = await legion.add_century(
            None,
            CenturyConfig(agent_type_name="claude_cli", min_legionaries=5),
            engine.registry,
            engine.scheduler,
            engine.event_bus,
        )
        futures = [await century.submit_task(p) for p in prompts]
        results = await asyncio.gather(*futures)
        await engine.shutdown()
    """

    def __init__(self, config: CenturionConfig | None = None) -> None:
        self.config = config or CenturionConfig()
        self.scheduler = CenturionScheduler(config=self.config)
        self.registry = AgentTypeRegistry()
        self.event_bus = EventBus(max_history=self.config.event_buffer_size)
        self.legions: dict[str, Legion] = {}
        self.broadcaster = Broadcaster(self)
        self.session_registry = SessionRegistry()
        self._shutting_down: bool = False
        self._register_default_types()

        # Sentinel service for stale session cleanup
        sentinel_config = SentinelConfig(
            scan_interval_seconds=self.config.sentinel_scan_interval,
            idle_threshold_seconds=self.config.sentinel_idle_threshold,
            max_runtime_seconds=self.config.sentinel_max_runtime,
            dry_run=self.config.sentinel_dry_run,
            enabled=self.config.sentinel_enabled,
        )
        self.sentinel = Sentinel(
            config=sentinel_config,
            session_registry=self.session_registry,
            event_bus=self.event_bus,
        )

        logger.info(
            "Engine initialized",
            extra={"config": {"max_agents": self.config.max_agents_hard_limit}},
        )

    def _register_default_types(self) -> None:
        # Lazy imports to avoid circular deps and allow optional deps
        from centurion.agent_types.claude_api import ClaudeApiAgentType
        from centurion.agent_types.claude_cli import ClaudeCliAgentType
        from centurion.agent_types.shell import ShellAgentType

        self.registry.register("claude_cli", ClaudeCliAgentType)
        self.registry.register("claude_api", ClaudeApiAgentType)
        self.registry.register("shell", ShellAgentType)

    async def raise_legion(
        self,
        legion_id: str | None = None,
        name: str = "",
        quota: LegionQuota | None = None,
    ) -> Legion:
        """Create a new legion (deployment group)."""
        legion_id = legion_id or f"legion-{uuid.uuid4().hex[:8]}"
        if legion_id in self.legions:
            raise ValueError(f"Legion {legion_id!r} already exists")

        legion = Legion(legion_id=legion_id, name=name, quota=quota)
        self.legions[legion_id] = legion
        logger.info("Legion raised", extra={"legion_id": legion_id, "legion_name": name})
        await self.event_bus.emit(
            "legion_raised",
            entity_type="legion",
            entity_id=legion_id,
            payload={"name": name},
        )
        return legion

    async def disband_legion(self, legion_id: str) -> None:
        """Disband a legion — terminate all its agents."""
        legion = self.legions.pop(legion_id, None)
        if legion is None:
            raise KeyError(f"Legion {legion_id!r} not found")

        await legion.dismiss_all()
        logger.info("Legion disbanded", extra={"legion_id": legion_id})
        await self.event_bus.emit(
            "legion_disbanded",
            entity_type="legion",
            entity_id=legion_id,
        )

    def get_legion(self, legion_id: str) -> Legion:
        legion = self.legions.get(legion_id)
        if legion is None:
            raise KeyError(f"Legion {legion_id!r} not found")
        return legion

    async def broadcast(
        self, message: str, target: str = "all", target_id: str | None = None
    ) -> dict:
        """Broadcast a message to agents.

        Args:
            message: The message/instruction to broadcast
            target: "all", "legion", or "century"
            target_id: Required when target is "legion" or "century"

        Returns dict with delivery stats.
        """
        if target == "all":
            total_delivered = 0
            total_failed = 0
            legion_results = {}
            for legion_id, legion in self.legions.items():
                result = await legion.broadcast(message)
                total_delivered += result["total_delivered"]
                total_failed += result["total_failed"]
                legion_results[legion_id] = result
            stats = {
                "target": "all",
                "total_delivered": total_delivered,
                "total_failed": total_failed,
                "legions": legion_results,
            }
        elif target == "legion":
            if not target_id:
                raise ValueError("target_id is required when target is 'legion'")
            legion = self.get_legion(target_id)
            stats = await legion.broadcast(message)
            stats["target"] = "legion"
        elif target == "century":
            if not target_id:
                raise ValueError("target_id is required when target is 'century'")
            century = None
            for legion in self.legions.values():
                if target_id in legion.centuries:
                    century = legion.centuries[target_id]
                    break
            if century is None:
                raise KeyError(f"Century {target_id!r} not found")
            results = await century.broadcast(message)
            delivered = sum(1 for r in results if r.get("delivered"))
            stats = {
                "target": "century",
                "target_id": target_id,
                "total_delivered": delivered,
                "total_failed": len(results) - delivered,
                "legionaries": results,
            }
        else:
            raise ValueError(f"Invalid target: {target!r}. Must be 'all', 'legion', or 'century'")

        await self.event_bus.emit(
            "broadcast_sent",
            entity_type="broadcast",
            payload={
                "target": target,
                "target_id": target_id,
                "message_length": len(message),
                "total_delivered": stats["total_delivered"],
                "total_failed": stats["total_failed"],
            },
        )
        return stats

    def fleet_status(self) -> dict:
        """Macro-level status of the entire engine."""
        total_centuries = 0
        total_legionaries = 0
        for legion in self.legions.values():
            total_centuries += len(legion.centuries)
            total_legionaries += legion.total_legionaries

        return {
            "total_legions": len(self.legions),
            "total_centuries": total_centuries,
            "total_legionaries": total_legionaries,
            "legions": {lid: l.status_report() for lid, l in self.legions.items()},
            "hardware": self.scheduler.to_dict(),
        }

    def hardware_report(self) -> dict:
        """Hardware resources and scheduling state."""
        return self.scheduler.to_dict()

    async def shutdown(self) -> None:
        """Gracefully shut down the entire engine."""
        if self._shutting_down:
            logger.warning("shutdown: already in progress")
            return

        self._shutting_down = True
        timeout = self.config.shutdown_timeout
        logger.info("shutdown: starting, timeout=%ss", timeout)

        # Phase 0: Stop sentinel
        if self.sentinel.is_running:
            await self.sentinel.stop()

        # Phase 1: Stop accepting new tasks
        logger.info("shutdown: phase 1 — stop accepting new tasks")
        for legion in self.legions.values():
            for century in legion.centuries.values():
                century._running = False

        # Phase 2: Drain all legions
        logger.info("shutdown: phase 2 — draining legions")
        legion_ids = list(self.legions.keys())
        for legion_id in legion_ids:
            try:
                await self.disband_legion(legion_id)
            except KeyError:
                pass

        # Wait for any remaining in-progress tasks with configurable timeout
        try:
            await asyncio.wait_for(self._drain_all(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("shutdown: drain timed out after %ss", timeout)

        # Terminate any remaining legions
        for legion in list(self.legions.values()):
            await legion.dismiss_all()
        self.legions.clear()

        # Phase 3: Complete
        logger.info("shutdown: complete")

    async def _drain_all(self) -> None:
        """Wait for all task queues to drain."""
        for legion in self.legions.values():
            for century in legion.centuries.values():
                if century.task_queue.qsize() > 0:
                    await century.task_queue.join()
