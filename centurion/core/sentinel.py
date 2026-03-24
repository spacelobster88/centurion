"""Sentinel — background service that scans and kills stale sessions/tasks.

Runs as a persistent async task within the Centurion engine.  Periodically
sweeps for stale sessions based on configurable thresholds, archives their
output before killing, and emits events + metrics for observability.

Session priority ordering (from CLAUDE.md):
  1. Stale/idle interactive sessions -> kill FIRST (lowest priority)
  2. Active interactive sessions     -> kill second
  3. Background Claude sessions      -> kill LAST (highest priority, producers)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from centurion.core.events import EventBus
    from centurion.core.session_registry import SessionMeta, SessionRegistry


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SentinelConfig:
    """Configurable thresholds for the sentinel service."""

    scan_interval_seconds: float = 300.0  # 5 minutes
    idle_threshold_seconds: float = 1800.0  # 30 minutes
    max_runtime_seconds: float = 7200.0  # 2 hours
    graceful_kill_timeout_seconds: float = 10.0  # SIGTERM -> SIGKILL wait
    dry_run: bool = False
    enabled: bool = True


# ---------------------------------------------------------------------------
# Kill metrics tracker
# ---------------------------------------------------------------------------

@dataclass
class SentinelKillRecord:
    """A single kill event recorded by the sentinel."""

    session_id: str
    session_type: str
    reason: str
    idle_seconds: float
    runtime_seconds: float
    timestamp: float
    dry_run: bool = False


class SentinelMetrics:
    """Thread-safe metrics for sentinel kills."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_kills: int = 0
        self._dry_run_kills: int = 0
        self._kills_by_type: dict[str, int] = {"interactive": 0, "background": 0}
        self._last_scan_at: float | None = None
        self._last_kill: SentinelKillRecord | None = None
        self._recent_kills: list[SentinelKillRecord] = []
        self._scans_completed: int = 0

    def record_kill(self, record: SentinelKillRecord) -> None:
        with self._lock:
            if record.dry_run:
                self._dry_run_kills += 1
            else:
                self._total_kills += 1
                self._kills_by_type[record.session_type] = (
                    self._kills_by_type.get(record.session_type, 0) + 1
                )
            self._last_kill = record
            self._recent_kills.append(record)
            # Keep last 50 kill records
            if len(self._recent_kills) > 50:
                self._recent_kills = self._recent_kills[-50:]

    def record_scan(self) -> None:
        with self._lock:
            self._last_scan_at = time.time()
            self._scans_completed += 1

    @property
    def total_kills(self) -> int:
        with self._lock:
            return self._total_kills

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_kills": self._total_kills,
                "dry_run_kills": self._dry_run_kills,
                "kills_by_type": dict(self._kills_by_type),
                "last_scan_at": self._last_scan_at,
                "scans_completed": self._scans_completed,
                "last_kill": (
                    {
                        "session_id": self._last_kill.session_id,
                        "session_type": self._last_kill.session_type,
                        "reason": self._last_kill.reason,
                        "idle_seconds": round(self._last_kill.idle_seconds, 1),
                        "runtime_seconds": round(self._last_kill.runtime_seconds, 1),
                        "timestamp": self._last_kill.timestamp,
                        "dry_run": self._last_kill.dry_run,
                    }
                    if self._last_kill
                    else None
                ),
                "recent_kills": [
                    {
                        "session_id": r.session_id,
                        "session_type": r.session_type,
                        "reason": r.reason,
                        "timestamp": r.timestamp,
                        "dry_run": r.dry_run,
                    }
                    for r in self._recent_kills[-10:]
                ],
            }


# ---------------------------------------------------------------------------
# Session priority for kill ordering
# ---------------------------------------------------------------------------

_SESSION_KILL_PRIORITY = {
    # Lower number = killed first
    "interactive": 0,
    "background": 1,
}


def _kill_priority(session_type: str) -> int:
    """Return kill priority for a session type. Lower = killed first."""
    return _SESSION_KILL_PRIORITY.get(session_type, 0)


# ---------------------------------------------------------------------------
# Sentinel service
# ---------------------------------------------------------------------------

class Sentinel:
    """Background sentinel that scans for and kills stale sessions.

    Usage::

        sentinel = Sentinel(config, session_registry, event_bus)
        await sentinel.start()   # begins background scanning
        ...
        await sentinel.stop()    # graceful shutdown

    The sentinel can also be triggered manually::

        results = await sentinel.scan_once()
    """

    def __init__(
        self,
        config: SentinelConfig | None = None,
        session_registry: SessionRegistry | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.config = config or SentinelConfig()
        self.session_registry = session_registry
        self.event_bus = event_bus
        self.metrics = SentinelMetrics()
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the sentinel background loop."""
        if not self.config.enabled:
            logger.info("Sentinel is disabled, not starting")
            return
        if self._running:
            logger.warning("Sentinel already running")
            return

        self._running = True
        self._task = asyncio.ensure_future(self._loop())
        logger.info(
            "Sentinel started: scan_interval=%.0fs idle_threshold=%.0fs "
            "max_runtime=%.0fs dry_run=%s",
            self.config.scan_interval_seconds,
            self.config.idle_threshold_seconds,
            self.config.max_runtime_seconds,
            self.config.dry_run,
        )

    async def stop(self) -> None:
        """Stop the sentinel background loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("Sentinel stopped")

    async def _loop(self) -> None:
        """Background loop: sleep, scan, repeat."""
        try:
            while self._running:
                await asyncio.sleep(self.config.scan_interval_seconds)
                if not self._running:
                    break
                try:
                    await self.scan_once()
                except Exception:
                    logger.exception("Sentinel scan failed")
        except asyncio.CancelledError:
            pass

    async def scan_once(self) -> list[SentinelKillRecord]:
        """Perform a single scan. Returns list of kill records.

        This is the core logic:
        1. Enumerate all active sessions from the registry
        2. Identify stale sessions (idle > threshold OR runtime > max)
        3. Sort by kill priority (interactive first, background last)
        4. Archive output (placeholder) and kill
        5. Log and emit events
        """
        if self.session_registry is None:
            logger.debug("Sentinel scan: no session registry, skipping")
            self.metrics.record_scan()
            return []

        now = time.time()
        stale_sessions: list[tuple[str, SessionMeta, str, float, float]] = []

        all_sessions = self.session_registry.get_all_sessions()
        for session_id, meta in all_sessions.items():
            if meta.status != "active":
                continue
            if meta.pinned:
                continue

            idle_seconds = now - meta.last_active
            runtime_seconds = now - meta.created_at

            # Check staleness criteria
            reason = None
            if idle_seconds >= self.config.idle_threshold_seconds:
                reason = f"idle for {idle_seconds:.0f}s (threshold: {self.config.idle_threshold_seconds:.0f}s)"
            elif runtime_seconds >= self.config.max_runtime_seconds:
                reason = f"running for {runtime_seconds:.0f}s (max: {self.config.max_runtime_seconds:.0f}s)"

            if reason is not None:
                # Check closeability — skip sessions with active bg children
                info = self.session_registry.closeable_info(session_id)
                if not info["closeable"]:
                    logger.debug(
                        "Sentinel: session %s is stale but not closeable: %s",
                        session_id,
                        info["reason"],
                    )
                    continue
                stale_sessions.append(
                    (session_id, meta, reason, idle_seconds, runtime_seconds)
                )

        # Sort by kill priority: interactive first, background last
        stale_sessions.sort(key=lambda s: _kill_priority(s[1].session_type))

        kills: list[SentinelKillRecord] = []
        for session_id, meta, reason, idle_seconds, runtime_seconds in stale_sessions:
            record = SentinelKillRecord(
                session_id=session_id,
                session_type=meta.session_type,
                reason=reason,
                idle_seconds=idle_seconds,
                runtime_seconds=runtime_seconds,
                timestamp=now,
                dry_run=self.config.dry_run,
            )

            if self.config.dry_run:
                logger.info(
                    "Sentinel [DRY RUN] would kill session %s (%s): %s",
                    session_id,
                    meta.session_type,
                    reason,
                )
            else:
                logger.info(
                    "Sentinel killing session %s (%s): %s",
                    session_id,
                    meta.session_type,
                    reason,
                )
                # Archive before killing (mark terminated in registry)
                self.session_registry.terminate_session(session_id)

            self.metrics.record_kill(record)
            kills.append(record)

            # Emit event
            if self.event_bus is not None:
                await self.event_bus.emit(
                    "sentinel_kill",
                    entity_type="session",
                    entity_id=session_id,
                    payload={
                        "session_type": meta.session_type,
                        "reason": reason,
                        "idle_seconds": round(idle_seconds, 1),
                        "runtime_seconds": round(runtime_seconds, 1),
                        "dry_run": self.config.dry_run,
                    },
                )

        self.metrics.record_scan()

        if kills:
            logger.info(
                "Sentinel scan complete: %d sessions killed (%s)",
                len(kills),
                "dry run" if self.config.dry_run else "live",
            )
        else:
            logger.debug("Sentinel scan complete: no stale sessions found")

        return kills
