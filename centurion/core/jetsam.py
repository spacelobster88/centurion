"""Jetsam detection — identify macOS Jetsam OOM kills on agent processes.

macOS Jetsam is the kernel-level OOM killer that sends SIGKILL (exit code -9
or 137) to processes when the system is under memory pressure. This module
provides utilities to detect and confirm Jetsam kills by querying the macOS
unified log system.
"""

from __future__ import annotations

import logging
import platform
import subprocess
import threading

logger = logging.getLogger(__name__)

# Exit codes that indicate a SIGKILL (potential Jetsam kill)
SIGKILL_EXIT_CODES = {-9, 137}


def is_sigkill(exit_code: int | None) -> bool:
    """Return True if the exit code indicates a SIGKILL."""
    return exit_code is not None and exit_code in SIGKILL_EXIT_CODES


def confirm_jetsam_kill(pid: int | None = None, seconds: int = 60) -> bool:
    """Query macOS unified log to confirm a Jetsam kill.

    Checks ``log show`` for Jetsam-related entries in the last ``seconds``
    seconds. If a ``pid`` is provided, looks for that specific PID in the
    Jetsam log entries.

    Returns True if Jetsam activity is confirmed, False otherwise.
    Always returns False on non-Darwin platforms.
    """
    if platform.system() != "Darwin":
        return False

    try:
        predicate = 'eventMessage contains "jetsam"'
        result = subprocess.run(
            [
                "log", "show",
                "--predicate", predicate,
                f"--last", f"{seconds}s",
                "--style", "compact",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.debug("confirm_jetsam_kill: log show failed rc=%d", result.returncode)
            return False

        output = result.stdout.lower()
        if "jetsam" not in output:
            return False

        # If we have a PID, check if it appears in the jetsam entries
        if pid is not None:
            # Look for the PID in jetsam-related lines
            for line in result.stdout.splitlines():
                if "jetsam" in line.lower() and str(pid) in line:
                    logger.info(
                        "confirm_jetsam_kill: confirmed Jetsam kill for pid=%d", pid,
                    )
                    return True
            # Jetsam activity found but not for this specific PID
            logger.debug(
                "confirm_jetsam_kill: Jetsam activity found but pid=%d not matched", pid,
            )
            # Still return True — Jetsam was active and a SIGKILL happened,
            # high probability this process was a victim
            return True

        logger.info("confirm_jetsam_kill: Jetsam activity confirmed (no pid filter)")
        return True

    except subprocess.TimeoutExpired:
        logger.warning("confirm_jetsam_kill: log show timed out")
        return False
    except Exception:
        logger.debug("confirm_jetsam_kill: failed to query logs", exc_info=True)
        return False


class JetsamTracker:
    """Thread-safe counter for Jetsam kill events.

    Tracks total Jetsam kills across the lifetime of the Centurion process.
    Exposed via the health/metrics endpoint.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._kill_count: int = 0
        self._last_kill_details: dict | None = None

    def record_kill(self, legionary_id: str, exit_code: int | None = None, confirmed: bool = False) -> None:
        """Record a Jetsam kill event."""
        with self._lock:
            self._kill_count += 1
            self._last_kill_details = {
                "legionary_id": legionary_id,
                "exit_code": exit_code,
                "confirmed_via_log": confirmed,
                "total_kills": self._kill_count,
            }
        logger.warning(
            "Jetsam kill recorded: legionary_id=%s exit_code=%s confirmed=%s total=%d",
            legionary_id, exit_code, confirmed, self._kill_count,
        )

    @property
    def kill_count(self) -> int:
        with self._lock:
            return self._kill_count

    @property
    def last_kill_details(self) -> dict | None:
        with self._lock:
            return self._last_kill_details.copy() if self._last_kill_details else None

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "jetsam_kill_count": self._kill_count,
                "last_jetsam_kill": self._last_kill_details,
            }
