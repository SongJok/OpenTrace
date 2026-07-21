"""
In-Process EventBus — async pub/sub for DAG lifecycle events.

Events emitted:
  dag.started   dag.completed
  task.started  task.succeeded  task.failed  task.retrying  task.skipped  task.dynamic
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from infra.observability.logger import get_logger

logger = get_logger(__name__)

Listener = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    """
    Lightweight in-process async event bus.
    Listener errors are caught and logged — they never block the engine.
    Supports wildcard '*' to receive all events.
    """

    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = {}

    def subscribe(self, event: str, fn: Listener) -> None:
        """Register an async listener for an event name (or '*' for all)."""
        self._listeners.setdefault(event, []).append(fn)
        logger.debug("EventBus subscribed", event=event)

    def unsubscribe(self, event: str, fn: Listener) -> None:
        listeners = self._listeners.get(event, [])
        if fn in listeners:
            listeners.remove(fn)

    async def publish(self, event: str, data: dict[str, Any]) -> None:
        """Publish an event — fires all matching + wildcard listeners concurrently."""
        targets = (
            self._listeners.get(event, [])
            + self._listeners.get("*", [])
        )
        if not targets:
            return
        payload = {"event": event, **data}
        await asyncio.gather(
            *[self._safe_call(fn, payload) for fn in targets],
            return_exceptions=True,
        )

    async def _safe_call(self, fn: Listener, data: dict[str, Any]) -> None:
        try:
            await fn(data)
        except Exception as exc:  # noqa: BLE001
            logger.error("EventBus listener error", error=str(exc))


# Module-level singleton — DAGEngine uses this by default
event_bus = EventBus()
