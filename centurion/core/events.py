"""EventBus — pub-sub system for real-time Centurion events (the Aquilifer)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CenturionEvent:
    """A single event emitted by the engine."""

    event_type: str
    entity_type: str | None = None
    entity_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(
            {
                "event_type": self.event_type,
                "entity_type": self.entity_type,
                "entity_id": self.entity_id,
                "payload": self.payload,
                "timestamp": self.timestamp,
            },
            default=str,
        )


class EventBus:
    """Async pub-sub event bus. Subscribers receive events via asyncio.Queue."""

    def __init__(self, max_history: int = 1000) -> None:
        self._subscribers: list[asyncio.Queue[CenturionEvent]] = []
        self._history: list[CenturionEvent] = []
        self._max_history = max_history

    def subscribe(self) -> asyncio.Queue[CenturionEvent]:
        queue: asyncio.Queue[CenturionEvent] = asyncio.Queue()
        self._subscribers.append(queue)
        logger.debug("subscribe: new subscriber total=%d", len(self._subscribers))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[CenturionEvent]) -> None:
        try:
            self._subscribers.remove(queue)
            logger.debug("unsubscribe: subscriber removed total=%d", len(self._subscribers))
        except ValueError:
            pass

    async def emit(
        self,
        event_type: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> CenturionEvent:
        event = CenturionEvent(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
        )
        logger.debug("emit: event_type=%s entity_type=%s entity_id=%s", event_type, entity_type, entity_id)
        # Store in ring buffer
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        # Broadcast to all subscribers (non-blocking)
        dropped = 0
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dropped += 1
        if dropped:
            logger.warning("emit: dropped event for %d/%d slow subscribers", dropped, len(self._subscribers))
        return event

    def recent_events(self, limit: int = 50) -> list[CenturionEvent]:
        return list(reversed(self._history[-limit:]))
