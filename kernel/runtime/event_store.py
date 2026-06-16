"""
RuntimeEventStore — Persist cognitive runtime events for audit and replay.

Records every significant event in a turn: plan, agent_result, fusion, critic,
answer.  Used for debugging, tracing, and future replay capabilities.

Schema (managed by Alembic migration):
  CREATE TABLE runtime_events (
      id VARCHAR(36) PRIMARY KEY,
      session_id VARCHAR(36) NOT NULL,
      turn_id VARCHAR(64) NOT NULL,
      event_type VARCHAR(50) NOT NULL,
      event_index INTEGER NOT NULL,
      payload JSONB NOT NULL,
      created_at TIMESTAMPTZ DEFAULT now()
  );
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


class RuntimeEvent:
    """A single cognitive runtime event."""

    def __init__(
        self,
        event_type: str,
        payload: dict[str, Any],
        session_id: str = "",
        turn_id: str = "",
    ) -> None:
        self.id = str(uuid.uuid4())
        self.session_id = session_id
        self.turn_id = turn_id or str(uuid.uuid4())
        self.event_type = event_type  # plan | agent_result | fusion | critic | answer
        self.payload = payload
        self.created_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "event_type": self.event_type,
            "event_index": 0,  # set by store on append
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
        }


class RuntimeEventStore:
    """Append-only event store for cognitive runtime events.

    Events are persisted to the runtime_events table for audit trail.
    Falls back to in-memory storage when the database is unavailable.
    """

    def __init__(self) -> None:
        self._buffer: list[RuntimeEvent] = []
        self._index: int = 0

    async def append(self, event: RuntimeEvent) -> None:
        """Record an event."""
        self._index += 1
        event.payload["_event_index"] = self._index
        self._buffer.append(event)
        logger.debug(
            "Runtime event recorded",
            event_type=event.event_type,
            turn_id=event.turn_id,
            index=self._index,
        )

    async def flush(self) -> None:
        """Persist buffered events to database."""
        if not self._buffer:
            return

        try:
            from infra.db.connection import get_db_session

            async with get_db_session() as session:
                for ev in self._buffer:
                    await session.execute(
                        """
                        INSERT INTO runtime_events (id, session_id, turn_id, event_type,
                            event_index, payload, created_at)
                        VALUES (:id, :session_id, :turn_id, :event_type,
                            :event_index, :payload, :created_at)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        {
                            "id": ev.id,
                            "session_id": ev.session_id,
                            "turn_id": ev.turn_id,
                            "event_type": ev.event_type,
                            "event_index": self._index,
                            "payload": json.dumps(ev.payload, ensure_ascii=False),
                            "created_at": ev.created_at,
                        },
                    )
                await session.commit()
            logger.info("Runtime events flushed", count=len(self._buffer))
        except Exception as exc:
            logger.warning("Failed to flush runtime events to DB", error=str(exc))
        finally:
            self._buffer.clear()

    async def get_turn_events(self, turn_id: str) -> list[dict[str, Any]]:
        """Retrieve all events for a given turn."""
        try:
            from infra.db.connection import get_db_session

            async with get_db_session() as session:
                result = await session.execute(
                    """
                    SELECT id, event_type, event_index, payload, created_at
                    FROM runtime_events
                    WHERE turn_id = :turn_id
                    ORDER BY event_index ASC
                    """,
                    {"turn_id": turn_id},
                )
                rows = result.fetchall()
                return [
                    {
                        "id": row[0],
                        "event_type": row[1],
                        "event_index": row[2],
                        "payload": row[3],
                        "created_at": row[4].isoformat() if row[4] else "",
                    }
                    for row in rows
                ]
        except Exception as exc:
            logger.warning("Failed to query runtime events", error=str(exc))
            return []

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)
