"""SessionRegistry — parent-child session relationship tracking.

Maintains an in-memory registry of sessions with parent-child relationships,
metadata, and lifecycle state.  Thread-safe via threading.Lock.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class SessionMeta:
    """Metadata about a registered session."""

    session_type: Literal["interactive", "background"]
    created_at: float
    last_active: float
    status: Literal["active", "terminated"] = "active"
    pinned: bool = False


@dataclass
class SessionRegistry:
    """Tracks parent-child relationships between sessions.

    Data structures
    ---------------
    session_parents : dict[str, str | None]
        child_id -> parent_id (None if root session)
    session_children : dict[str, set[str]]
        parent_id -> set of child_ids
    session_meta : dict[str, SessionMeta]
        session_id -> metadata
    """

    session_parents: dict[str, str | None] = field(default_factory=dict)
    session_children: dict[str, set[str]] = field(default_factory=dict)
    session_meta: dict[str, SessionMeta] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_session(
        self,
        session_id: str,
        parent_id: str | None,
        session_type: Literal["interactive", "background"],
        pinned: bool = False,
    ) -> None:
        """Register a new session, optionally linking it to a parent."""
        now = time.time()
        with self._lock:
            if session_id in self.session_meta:
                raise ValueError(f"Session {session_id!r} already registered")

            self.session_meta[session_id] = SessionMeta(
                session_type=session_type,
                created_at=now,
                last_active=now,
                status="active",
                pinned=pinned,
            )
            self.session_parents[session_id] = parent_id

            if parent_id is not None:
                self.session_children.setdefault(parent_id, set()).add(session_id)

            # Ensure session_children entry exists for the new session.
            self.session_children.setdefault(session_id, set())

    def register_child(self, parent_id: str, child_id: str) -> None:
        """Link an existing child session to an existing parent session."""
        with self._lock:
            if parent_id not in self.session_meta:
                raise ValueError(f"Parent {parent_id!r} not registered")
            if child_id not in self.session_meta:
                raise ValueError(f"Child {child_id!r} not registered")

            self.session_parents[child_id] = parent_id
            self.session_children.setdefault(parent_id, set()).add(child_id)

    def unregister_session(self, session_id: str) -> None:
        """Remove a session and clean up relationship links.

        Children of this session become orphans (their parent link still
        references this session, but it no longer has metadata).
        Idempotent — no error if session_id is unknown.
        """
        with self._lock:
            if session_id not in self.session_meta:
                return

            # Remove from parent's children set.
            parent_id = self.session_parents.get(session_id)
            if parent_id is not None and parent_id in self.session_children:
                self.session_children[parent_id].discard(session_id)

            # Remove own metadata and parent link.
            del self.session_meta[session_id]
            self.session_parents.pop(session_id, None)

            # Keep session_children[session_id] — children still reference
            # this session as parent, but we remove the children set entry
            # since the parent is gone. The orphan detection uses session_meta
            # presence to determine if a parent is alive.
            self.session_children.pop(session_id, None)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_children(self, session_id: str) -> list[str]:
        """Return sorted list of child session IDs (empty if none or unknown)."""
        with self._lock:
            children = self.session_children.get(session_id, set())
            return sorted(children)

    def get_parent(self, session_id: str) -> str | None:
        """Return parent session ID, or None if root / unknown."""
        with self._lock:
            return self.session_parents.get(session_id)

    def is_orphan(self, session_id: str) -> bool:
        """True if the session has a parent that is terminated or unregistered."""
        with self._lock:
            if session_id not in self.session_meta:
                return False

            parent_id = self.session_parents.get(session_id)
            if parent_id is None:
                return False

            # Parent no longer registered.
            if parent_id not in self.session_meta:
                return True

            # Parent registered but terminated.
            return self.session_meta[parent_id].status == "terminated"

    def get_session_meta(self, session_id: str) -> SessionMeta | None:
        """Return metadata for a session, or None if unknown."""
        with self._lock:
            return self.session_meta.get(session_id)

    def get_all_sessions(self) -> dict[str, SessionMeta]:
        """Return a shallow copy of all session metadata."""
        with self._lock:
            return dict(self.session_meta)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def update_last_active(self, session_id: str) -> None:
        """Bump last_active to current time."""
        with self._lock:
            meta = self.session_meta.get(session_id)
            if meta is None:
                raise ValueError(f"Session {session_id!r} not registered")
            meta.last_active = time.time()

    def closeable_info(self, session_id: str) -> dict:
        """Return closeability information for a session.

        Returns a dict with:
        - has_bg_children: bool — are there active background children?
        - bg_child_ids: list[str] — IDs of active background children
        - closeable: bool — True if not pinned AND no active bg children
        - reason: str — human-readable explanation
        """
        with self._lock:
            meta = self.session_meta.get(session_id)

            # Compute active background children.
            active_bg_children: list[str] = []
            for child_id in sorted(self.session_children.get(session_id, set())):
                child_meta = self.session_meta.get(child_id)
                if child_meta is not None and child_meta.status == "active":
                    active_bg_children.append(child_id)

            has_bg_children = len(active_bg_children) > 0

            # Determine closeability and reason.
            if meta is not None and meta.pinned:
                closeable = False
                reason = "session is pinned"
            elif has_bg_children:
                closeable = False
                reason = f"has active background children: {active_bg_children}"
            else:
                closeable = True
                reason = "no active background children"

            return {
                "has_bg_children": has_bg_children,
                "bg_child_ids": active_bg_children,
                "closeable": closeable,
                "reason": reason,
            }

    def terminate_session(self, session_id: str) -> None:
        """Mark a session as terminated (keeps metadata for orphan detection)."""
        with self._lock:
            meta = self.session_meta.get(session_id)
            if meta is None:
                raise ValueError(f"Session {session_id!r} not registered")
            meta.status = "terminated"
