"""Broadcast — send messages to groups of active agents.

Supports broadcasting to:
- A single Century (row): all legionaries in one squad
- A single Legion (column): all legionaries across all centuries in a deployment group
- Fleet-wide (all): every active legionary in the engine

Broadcast messages are delivered as high-priority tasks (priority=1) to all
targeted agents simultaneously, bypassing the normal queue ordering.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from centurion.agent_types.base import AgentResult

if TYPE_CHECKING:
    from centurion.core.century import Century
    from centurion.core.engine import Centurion
    from centurion.core.events import EventBus
    from centurion.core.legion import Legion

logger = logging.getLogger(__name__)


@dataclass
class BroadcastResult:
    """Result of a broadcast operation."""

    broadcast_id: str
    scope: str  # "century", "legion", "fleet"
    target_id: str | None  # century_id or legion_id; None for fleet
    message: str
    total_targets: int = 0
    delivered: int = 0
    failed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "broadcast_id": self.broadcast_id,
            "scope": self.scope,
            "target_id": self.target_id,
            "message": self.message,
            "total_targets": self.total_targets,
            "delivered": self.delivered,
            "failed": self.failed,
            "results": self.results,
            "timestamp": self.timestamp,
        }


class Broadcaster:
    """Handles broadcast operations across the Centurion fleet."""

    def __init__(self, engine: Centurion) -> None:
        self.engine = engine

    async def broadcast_to_century(
        self, century_id: str, message: str, wait: bool = False
    ) -> BroadcastResult:
        """Broadcast a message to all legionaries in a specific century (row)."""
        century = self._find_century(century_id)
        if century is None:
            raise KeyError(f"Century {century_id!r} not found")

        broadcast_id = f"bc-{uuid.uuid4().hex[:8]}"
        result = BroadcastResult(
            broadcast_id=broadcast_id,
            scope="century",
            target_id=century_id,
            message=message,
        )

        futures = await self._deliver_to_century(century, message, broadcast_id)
        result.total_targets = len(futures)

        if wait and futures:
            result = await self._collect_results(result, futures)
        else:
            result.delivered = len(futures)

        await self._emit_broadcast_event(result)
        return result

    async def broadcast_to_legion(
        self, legion_id: str, message: str, wait: bool = False
    ) -> BroadcastResult:
        """Broadcast a message to all legionaries in a specific legion (column)."""
        legion = self.engine.legions.get(legion_id)
        if legion is None:
            raise KeyError(f"Legion {legion_id!r} not found")

        broadcast_id = f"bc-{uuid.uuid4().hex[:8]}"
        result = BroadcastResult(
            broadcast_id=broadcast_id,
            scope="legion",
            target_id=legion_id,
            message=message,
        )

        all_futures: list[asyncio.Future[AgentResult]] = []
        for century in legion.centuries.values():
            futures = await self._deliver_to_century(century, message, broadcast_id)
            all_futures.extend(futures)

        result.total_targets = len(all_futures)

        if wait and all_futures:
            result = await self._collect_results(result, all_futures)
        else:
            result.delivered = len(all_futures)

        await self._emit_broadcast_event(result)
        return result

    async def broadcast_to_fleet(
        self, message: str, wait: bool = False
    ) -> BroadcastResult:
        """Broadcast a message to all legionaries in the entire fleet."""
        broadcast_id = f"bc-{uuid.uuid4().hex[:8]}"
        result = BroadcastResult(
            broadcast_id=broadcast_id,
            scope="fleet",
            target_id=None,
            message=message,
        )

        all_futures: list[asyncio.Future[AgentResult]] = []
        for legion in self.engine.legions.values():
            for century in legion.centuries.values():
                futures = await self._deliver_to_century(century, message, broadcast_id)
                all_futures.extend(futures)

        result.total_targets = len(all_futures)

        if wait and all_futures:
            result = await self._collect_results(result, all_futures)
        else:
            result.delivered = len(all_futures)

        await self._emit_broadcast_event(result)
        return result

    # --- Internal helpers ---

    def _find_century(self, century_id: str):
        """Find a century across all legions."""
        for legion in self.engine.legions.values():
            if century_id in legion.centuries:
                return legion.centuries[century_id]
        return None

    async def _deliver_to_century(
        self, century: Century, message: str, broadcast_id: str
    ) -> list[asyncio.Future[AgentResult]]:
        """Submit the broadcast message to a century with highest priority."""
        futures: list[asyncio.Future[AgentResult]] = []
        for leg_id in list(century.legionaries.keys()):
            task_id = f"{broadcast_id}-{leg_id}"
            try:
                future = await century.submit_task(
                    prompt=message,
                    priority=1,  # Highest priority (broadcast)
                    task_id=task_id,
                )
                futures.append(future)
            except Exception as exc:
                logger.warning(
                    "Broadcast delivery failed for legionary %s: %s",
                    leg_id, exc,
                )
        return futures

    async def _collect_results(
        self,
        result: BroadcastResult,
        futures: list[asyncio.Future[AgentResult]],
    ) -> BroadcastResult:
        """Wait for all broadcast futures and collect results."""
        done = await asyncio.gather(*futures, return_exceptions=True)
        for item in done:
            if isinstance(item, Exception):
                result.failed += 1
                result.results.append({
                    "success": False,
                    "error": str(item),
                })
            else:
                if item.success:
                    result.delivered += 1
                else:
                    result.failed += 1
                result.results.append({
                    "success": item.success,
                    "output": item.output[:500] if item.output else None,
                    "error": item.error,
                    "legionary_id": item.legionary_id,
                })
        return result

    async def _emit_broadcast_event(self, result: BroadcastResult) -> None:
        """Emit a broadcast event via the event bus."""
        if self.engine.event_bus:
            await self.engine.event_bus.emit(
                "broadcast_sent",
                entity_type="broadcast",
                entity_id=result.broadcast_id,
                payload={
                    "scope": result.scope,
                    "target_id": result.target_id,
                    "total_targets": result.total_targets,
                    "delivered": result.delivered,
                    "failed": result.failed,
                },
            )
