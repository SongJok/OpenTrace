from __future__ import annotations

import json
from typing import Any

from infra.cache.redis_client import get_pubsub_redis
from infra.message_bus.events import CognitiveEvent


class EventStore:
    def __init__(self, namespace: str = "opentrace:cognitive") -> None:
        self.ns = namespace

    def stream_key(self) -> str:
        return f"{self.ns}:stream"

    def trace_index_key(self, trace_id: str) -> str:
        return f"{self.ns}:trace:{trace_id}"

    async def append(self, event: CognitiveEvent) -> str:
        redis = await get_pubsub_redis()
        payload = event.to_dict()
        event_id = await redis.xadd(self.stream_key(), {"data": json.dumps(payload, ensure_ascii=False)}, maxlen=200000)
        await redis.sadd(self.trace_index_key(event.trace_id), str(event_id))
        return str(event_id)

    async def list_by_trace(self, trace_id: str, limit: int = 200) -> list[dict[str, Any]]:
        redis = await get_pubsub_redis()
        entries = await redis.xrevrange(self.stream_key(), count=limit)
        result: list[dict[str, Any]] = []
        for _entry_id, fields in reversed(entries):
            raw = fields.get(b"data") if isinstance(fields, dict) else None
            if raw is None and isinstance(fields, dict):
                raw = fields.get("data")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if not isinstance(raw, str):
                continue
            try:
                item = json.loads(raw)
            except Exception:
                continue
            if str(item.get("trace_id")) == trace_id:
                result.append(item)
        return result
