"""CenturionDB — async database repository for tasks, events, and state."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import aiosqlite

from centurion.db.schema import CREATE_INDEXES, TABLES

if TYPE_CHECKING:
    from centurion.core.events import CenturionEvent


def _now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _row_to_dict(cursor: aiosqlite.Cursor, row: aiosqlite.Row) -> dict[str, Any]:
    """Convert a database row to a dictionary using column names."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class CenturionDB:
    """Async SQLite repository for Centurion persistence.

    Usage::

        db = CenturionDB("data/centurion.db")
        await db.init()
        await db.record_task(...)
        await db.close()
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Open the database connection and ensure all tables exist."""
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        for ddl in TABLES:
            await self._conn.execute(ddl)
        for idx in CREATE_INDEXES:
            await self._conn.execute(idx)
        await self._conn.commit()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call init() first.")
        return self._conn

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def record_task(
        self,
        task_id: str,
        century_id: str,
        legion_id: str,
        prompt: str,
        priority: int = 5,
    ) -> None:
        """Insert a new task record with 'pending' status."""
        await self.conn.execute(
            """
            INSERT INTO centurion_tasks (id, century_id, legion_id, prompt, priority, status, submitted_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (task_id, century_id, legion_id, prompt, priority, _now_iso()),
        )
        await self.conn.commit()

    async def update_task(
        self,
        task_id: str,
        status: str,
        legionary_id: str | None = None,
        output: str | None = None,
        error: str | None = None,
        exit_code: int | None = None,
        duration: float | None = None,
    ) -> None:
        """Update task fields. Only non-None values are written."""
        sets: list[str] = ["status = ?"]
        params: list[Any] = [status]

        if legionary_id is not None:
            sets.append("legionary_id = ?")
            params.append(legionary_id)
        if output is not None:
            sets.append("output = ?")
            params.append(output)
        if error is not None:
            sets.append("error = ?")
            params.append(error)
        if exit_code is not None:
            sets.append("exit_code = ?")
            params.append(exit_code)
        if duration is not None:
            sets.append("duration_seconds = ?")
            params.append(duration)

        # Set timestamp columns based on status transition
        if status == "running":
            sets.append("started_at = ?")
            params.append(_now_iso())
        elif status in ("completed", "failed", "cancelled"):
            sets.append("completed_at = ?")
            params.append(_now_iso())

        params.append(task_id)
        await self.conn.execute(
            f"UPDATE centurion_tasks SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        await self.conn.commit()

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Fetch a single task by ID."""
        cursor = await self.conn.execute("SELECT * FROM centurion_tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_dict(cursor, row)

    async def query_tasks(
        self,
        status: str | None = None,
        century_id: str | None = None,
        legion_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query tasks with optional filters."""
        conditions: list[str] = []
        params: list[Any] = []

        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if century_id is not None:
            conditions.append("century_id = ?")
            params.append(century_id)
        if legion_id is not None:
            conditions.append("legion_id = ?")
            params.append(legion_id)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM centurion_tasks {where} ORDER BY submitted_at DESC LIMIT ?"
        params.append(limit)

        cursor = await self.conn.execute(query, params)
        rows = await cursor.fetchall()
        return [_row_to_dict(cursor, row) for row in rows]

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def record_event(self, event: CenturionEvent) -> None:
        """Persist a CenturionEvent to the events table."""
        await self.conn.execute(
            """
            INSERT INTO centurion_events (event_type, entity_type, entity_id, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.event_type,
                event.entity_type,
                event.entity_id,
                json.dumps(event.payload, default=str) if event.payload else None,
                datetime.fromtimestamp(event.timestamp, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            ),
        )
        await self.conn.commit()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
