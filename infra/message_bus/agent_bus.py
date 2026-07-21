from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from infra.cache.redis_client import get_pubsub_redis
from infra.config.settings import settings
from infra.message_bus.cognitive_event_bus import cognitive_event_bus


@dataclass
class AgentTaskEnvelope:
    task_id: str
    agent_type: str
    query: str
    params: dict[str, Any]
    session_id: str | None = None
    user_id: str | None = None
    attempt: int = 0


class AgentMessageBus:
    def __init__(self, namespace: str = "opentrace:agent") -> None:
        self.ns = namespace
        self.mode = str(getattr(settings, "kernel_agent_bus_mode", "pubsub")).lower()
        self.group = str(getattr(settings, "kernel_agent_bus_group", "agent-workers"))
        self.consumer = str(getattr(settings, "kernel_agent_bus_consumer", "worker-1"))

    def task_channel(self, agent_type: str) -> str:
        return f"{self.ns}:task:{agent_type}"

    def task_stream(self, agent_type: str) -> str:
        return f"{self.ns}:stream:task:{agent_type}"

    def dlq_stream(self) -> str:
        override = str(getattr(settings, "kernel_agent_bus_dlq_stream", "") or "").strip()
        return override if override else f"{self.ns}:stream:dlq"

    def result_channel(self, task_id: str) -> str:
        return f"{self.ns}:result:{task_id}"

    def result_key(self, task_id: str) -> str:
        return f"{self.ns}:result:key:{task_id}"

    async def _payload(self, task: AgentTaskEnvelope) -> dict[str, Any]:
        return {
            "ts": time.time(),
            "task_id": task.task_id,
            "agent_type": task.agent_type,
            "query": task.query,
            "params": task.params,
            "session_id": task.session_id,
            "user_id": task.user_id,
            "attempt": int(task.attempt or 0),
        }

    async def publish_task(self, task: AgentTaskEnvelope) -> None:
        r = await get_pubsub_redis()
        payload = await self._payload(task)
        trace_id = str(payload.get("session_id") or payload.get("task_id") or task.task_id)
        await cognitive_event_bus.publish(
            cognitive_event_bus.emit_execution(
                trace_id=trace_id,
                payload={
                    "action": "publish_task",
                    "task_id": task.task_id,
                    "agent_type": task.agent_type,
                    "query": task.query,
                    "params": task.params,
                    "session_id": task.session_id,
                    "user_id": task.user_id,
                    "attempt": int(task.attempt or 0),
                },
                source="agent_bus",
                actor=task.agent_type,
            )
        )
        if self.mode == "stream":
            await r.xadd(self.task_stream(task.agent_type), {"data": json.dumps(payload, ensure_ascii=False)}, maxlen=10000)
            return
        await r.publish(self.task_channel(task.agent_type), json.dumps(payload, ensure_ascii=False))

    async def publish_result(self, task_id: str, result: dict[str, Any]) -> None:
        r = await get_pubsub_redis()
        body = json.dumps({"ts": time.time(), **result}, ensure_ascii=False)
        await r.setex(self.result_key(task_id), 120, body)
        await cognitive_event_bus.publish(
            cognitive_event_bus.emit_execution(
                trace_id=str(result.get("session_id") or task_id),
                payload={"action": "publish_result", "task_id": task_id, "result": result},
                source="agent_bus",
                actor="agent-worker",
            )
        )
        if self.mode == "stream":
            await r.xadd(f"{self.ns}:stream:result", {"task_id": task_id, "data": body}, maxlen=20000)
            return
        await r.publish(self.result_channel(task_id), body)

    async def wait_for_result(self, task_id: str, timeout_sec: int = 30) -> dict[str, Any]:
        if self.mode == "stream":
            r = await get_pubsub_redis()
            end = time.time() + timeout_sec
            while time.time() < end:
                cached = await r.get(self.result_key(task_id))
                if isinstance(cached, str) and cached:
                    return json.loads(cached)
                await asyncio.sleep(0.2)
            raise asyncio.TimeoutError

        r = await get_pubsub_redis()
        ps = r.pubsub()
        await ps.subscribe(self.result_channel(task_id))

        async def _listen() -> dict[str, Any]:
            async for msg in ps.listen():
                if msg.get("type") != "message":
                    continue
                data = msg.get("data")
                if isinstance(data, str):
                    return json.loads(data)
            return {"status": "error", "error": "bus_closed"}

        try:
            return await asyncio.wait_for(_listen(), timeout=timeout_sec)
        finally:
            await ps.unsubscribe(self.result_channel(task_id))
            await ps.close()

    async def ensure_stream_group(self, agent_type: str) -> None:
        if self.mode != "stream":
            return
        r = await get_pubsub_redis()
        stream = self.task_stream(agent_type)
        try:
            await r.xgroup_create(stream, self.group, id="0", mkstream=True)
        except Exception:
            # likely BUSYGROUP
            return
