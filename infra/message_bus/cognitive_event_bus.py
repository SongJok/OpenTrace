from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from infra.cache.redis_client import get_pubsub_redis
from infra.config.settings import settings
from infra.message_bus.event_store import EventStore
from infra.message_bus.events import CognitiveEvent, CognitiveEventType
from infra.observability.logger import get_logger

logger = get_logger(__name__)

EventHandler = Callable[[CognitiveEvent], Awaitable[None]]


class CognitiveEventBus:
    def __init__(self, namespace: str = "opentrace:cognitive") -> None:
        self.ns = namespace
        self.mode = str(getattr(settings, "kernel_event_bus_mode", "event-log")).lower()
        self.enabled = bool(getattr(settings, "kernel_event_bus_enabled", False))
        self.trace_required = bool(getattr(settings, "kernel_event_bus_trace_required", True))
        self.permission_enforced = bool(getattr(settings, "kernel_event_bus_permission_enforced", True))
        self.replay_enabled = bool(getattr(settings, "kernel_event_bus_replay_enabled", True))
        self.store = EventStore(namespace=namespace)

    def channel(self, event_type: CognitiveEventType) -> str:
        return f"{self.ns}:event:{event_type.value}"

    def _validate(self, event: CognitiveEvent) -> None:
        if self.trace_required and not event.trace_id:
            raise ValueError("trace_id is required for cognitive events")
        if not event.timestamp:
            raise ValueError("timestamp is required for cognitive events")

    async def publish(self, event: CognitiveEvent) -> None:
        self._validate(event)
        try:
            await self.store.append(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cognitive event store unavailable", error=str(exc), event_type=event.event_type.value)
        if not self.enabled:
            return
        try:
            redis = await get_pubsub_redis()
            payload = json.dumps(event.to_dict(), ensure_ascii=False)
            if self.mode == "stream":
                await redis.xadd(self.channel(event.event_type), {"data": payload}, maxlen=50000)
            else:
                await redis.publish(self.channel(event.event_type), payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cognitive event bus publish failed", error=str(exc), event_type=event.event_type.value)

    async def subscribe(self, event_type: CognitiveEventType, handler: EventHandler) -> None:
        redis = await get_pubsub_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(self.channel(event_type))
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            if not isinstance(data, str):
                continue
            try:
                await handler(CognitiveEvent.from_dict(json.loads(data)))
            except Exception as exc:  # noqa: BLE001
                logger.error("cognitive event handler error", event_type=event_type.value, error=str(exc))

    async def replay(self, trace_id: str, limit: int = 200) -> list[CognitiveEvent]:
        if not self.replay_enabled:
            return []
        rows = await self.store.list_by_trace(trace_id, limit=limit)
        return [CognitiveEvent.from_dict(row) for row in rows]

    def emit_planning(self, trace_id: str, payload: dict[str, Any], **meta: Any) -> CognitiveEvent:
        return CognitiveEvent(event_type=CognitiveEventType.PLANNING, trace_id=trace_id, payload=payload, **meta)

    def emit_execution(self, trace_id: str, payload: dict[str, Any], **meta: Any) -> CognitiveEvent:
        return CognitiveEvent(event_type=CognitiveEventType.EXECUTION, trace_id=trace_id, payload=payload, **meta)

    def emit_evidence(self, trace_id: str, payload: dict[str, Any], **meta: Any) -> CognitiveEvent:
        return CognitiveEvent(event_type=CognitiveEventType.EVIDENCE, trace_id=trace_id, payload=payload, **meta)

    def emit_critic(self, trace_id: str, payload: dict[str, Any], **meta: Any) -> CognitiveEvent:
        return CognitiveEvent(event_type=CognitiveEventType.CRITIC, trace_id=trace_id, payload=payload, **meta)

    def emit_feedback(self, trace_id: str, payload: dict[str, Any], **meta: Any) -> CognitiveEvent:
        return CognitiveEvent(event_type=CognitiveEventType.FEEDBACK, trace_id=trace_id, payload=payload, **meta)

    def emit_learning(self, trace_id: str, payload: dict[str, Any], **meta: Any) -> CognitiveEvent:
        return CognitiveEvent(event_type=CognitiveEventType.LEARNING, trace_id=trace_id, payload=payload, **meta)


cognitive_event_bus = CognitiveEventBus()
