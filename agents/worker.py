"""Agent Worker — 订阅 Agent 总线并调度各 Agent 执行能力任务。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from agents.base import TaskMessage
from agents.bootstrap import (
    instantiate_builtin_agents,
    is_builtin_agent_enabled,
    register_builtin_agents,
)
from infra.config.settings import settings
from infra.message_bus.agent_bus import AgentMessageBus


class AgentWorker:
    def __init__(self) -> None:
        self.bus = AgentMessageBus(namespace=str(settings.kernel_agent_bus_namespace))

        register_builtin_agents(force=True)
        self.agents: dict[str, Any] = instantiate_builtin_agents()

        from kernel.runtime.capability import capability_registry

        for agent in self.agents.values():
            if not capability_registry.has_agent(agent.agent_type):
                capability_registry.register_agent(agent)

    async def _execute_payload(self, agent_type: str, payload: dict, attempt: int = 0) -> None:
        task = TaskMessage(
            task_id=str(payload.get("task_id", "")),
            agent_type=agent_type,
            query=str(payload.get("query", "")),
            params=payload.get("params") or {},
            session_id=payload.get("session_id"),
            user_id=payload.get("user_id"),
        )
        agent = self.agents[agent_type]
        goal_id = str((payload.get("params") or {}).get("goal_id") or payload.get("goal_id") or "")
        trace_id = str(payload.get("request_id") or payload.get("trace_id") or "")
        if bool(getattr(settings, "kernel_agent_runtime_v3_enabled", True)):
            from kernel.agent_runtime.executor import agent_runtime_executor

            contrib = await agent_runtime_executor.execute_task(
                agent,
                task,
                goal_id=goal_id,
                goal_description=str(payload.get("goal_description") or ""),
                trace_id=trace_id,
            )
            res = agent_runtime_executor.contribution_to_agent_result(contrib)
        else:
            res = await agent.execute(task)

        max_retry = int(getattr(settings, "kernel_agent_bus_max_retry", 2))
        if res.status in {"error", "timeout"} and attempt < max_retry:
            retry_payload = {**payload, "attempt": attempt + 1, "last_error": res.error}
            from infra.message_bus.agent_bus import AgentTaskEnvelope

            await self.bus.publish_task(
                AgentTaskEnvelope(
                    task_id=task.task_id,
                    agent_type=agent_type,
                    query=task.query,
                    params=retry_payload.get("params") or {},
                    session_id=task.session_id,
                    user_id=task.user_id,
                    attempt=attempt + 1,
                )
            )
            return

        if res.status in {"error", "timeout"} and attempt >= max_retry:
            from infra.cache.redis_client import get_pubsub_redis

            r = await get_pubsub_redis()
            await r.xadd(
                self.bus.dlq_stream(),
                {
                    "data": json.dumps(
                        {
                            "task_id": task.task_id,
                            "agent_type": agent_type,
                            "query": task.query,
                            "params": payload.get("params") or {},
                            "session_id": task.session_id,
                            "user_id": task.user_id,
                            "attempt": attempt,
                            "error": res.error,
                        },
                        ensure_ascii=False,
                    )
                },
                maxlen=20000,
            )

        await self.bus.publish_result(task.task_id, res.model_dump(mode="json"))

    async def _consume_pubsub(self, agent_type: str) -> None:
        r = await __import__(
            "infra.cache.redis_client", fromlist=["get_pubsub_redis"]
        ).get_pubsub_redis()
        ps = r.pubsub()
        ch = self.bus.task_channel(agent_type)
        await ps.subscribe(ch)
        async for msg in ps.listen():
            if msg.get("type") != "message":
                continue
            data = msg.get("data")
            if not isinstance(data, str):
                continue
            payload = json.loads(data)
            attempt = int(payload.get("attempt", 0) or 0)
            await self._execute_payload(agent_type, payload, attempt=attempt)

    async def _reclaim_pending(self, r, stream: str, agent_type: str) -> None:
        idle_ms = int(getattr(settings, "kernel_agent_bus_reclaim_idle_ms", 30000))
        reclaim_count = int(getattr(settings, "kernel_agent_bus_reclaim_count", 20))
        pending = await r.xpending_range(
            stream, self.bus.group, min="-", max="+", count=reclaim_count
        )
        if not pending:
            return
        ids = []
        for p in pending:
            msg_id = p.get("message_id") or p.get("message_id")
            idle = int(p.get("time_since_delivered", 0) or 0)
            if msg_id and idle >= idle_ms:
                ids.append(msg_id)
        if not ids:
            return
        claimed = await r.xclaim(
            stream, self.bus.group, self.bus.consumer, min_idle_time=idle_ms, message_ids=ids
        )
        for msg_id, fields in claimed:
            data = fields.get("data")
            if not isinstance(data, str):
                await r.xack(stream, self.bus.group, msg_id)
                continue
            payload = json.loads(data)
            attempt = int(payload.get("attempt", 0) or 0)
            await self._execute_payload(agent_type, payload, attempt=attempt)
            await r.xack(stream, self.bus.group, msg_id)

    async def _consume_stream(self, agent_type: str) -> None:
        from infra.cache.redis_client import get_pubsub_redis

        await self.bus.ensure_stream_group(agent_type)
        r = await get_pubsub_redis()
        stream = self.bus.task_stream(agent_type)
        while True:
            rows = await r.xreadgroup(
                self.bus.group,
                self.bus.consumer,
                streams={stream: ">"},
                count=10,
                block=1000,
            )
            if rows:
                for _, entries in rows:
                    for msg_id, fields in entries:
                        data = fields.get("data")
                        if not isinstance(data, str):
                            await r.xack(stream, self.bus.group, msg_id)
                            continue
                        payload = json.loads(data)
                        attempt = int(payload.get("attempt", 0) or 0)
                        await self._execute_payload(agent_type, payload, attempt=attempt)
                        await r.xack(stream, self.bus.group, msg_id)
            await self._reclaim_pending(r, stream, agent_type)

    async def _consume(self, agent_type: str) -> None:
        if self.bus.mode == "stream":
            await self._consume_stream(agent_type)
            return
        await self._consume_pubsub(agent_type)

    async def _heartbeat(self) -> None:
        import time

        from infra.cache.redis_client import get_pubsub_redis

        ns = str(getattr(settings, "kernel_agent_bus_namespace", "opentrace:agent"))
        key = f"{ns}:worker:heartbeat"
        while True:
            try:
                r = await get_pubsub_redis()
                await r.setex(key, 60, str(int(time.time())))
            except Exception:
                pass
            await asyncio.sleep(10)

    def _bus_consumer_agent_types(self) -> tuple[str, ...]:
        from kernel.agent_runtime.manifest import get_manifest

        manifest = get_manifest()
        eligible = set(manifest.bus_eligible_agent_types())
        return tuple(
            agent_type
            for agent_type in self.agents
            if agent_type in eligible and is_builtin_agent_enabled(agent_type)
        )

    async def run_forever(self) -> None:
        consumers = self._bus_consumer_agent_types()
        from infra.message_bus.subscribers import memory_event_subscriber
        from infra.response_worker import response_job_loop
        from infra.responses.scheduler import scheduler_loop
        from knowledge.jobs import knowledge_job_loop
        from services.company_brain import company_brain_worker_loop
        from services.data_governance import deletion_job_loop
        from skills.catalog import skillhub_sync_loop

        role = str(settings.worker_role or "all")
        tasks = [self._heartbeat()]
        if role in {"all", "responses"}:
            tasks.append(response_job_loop())
        if role in {"all", "knowledge"}:
            tasks.extend((knowledge_job_loop(), skillhub_sync_loop()))
        if role in {"all", "scheduler"}:
            tasks.extend(
                (
                    scheduler_loop(),
                    company_brain_worker_loop(),
                    deletion_job_loop(),
                )
            )
        if role in {"all", "agents"}:
            tasks.append(memory_event_subscriber.start())
            tasks.extend(self._consume(agent_type) for agent_type in consumers)
        await asyncio.gather(*tasks)


async def main() -> None:
    if int(settings.worker_metrics_port) > 0:
        from prometheus_client import start_http_server

        start_http_server(int(settings.worker_metrics_port))
    if settings.trace_enabled:
        from infra.observability.tracer import setup_tracing

        setup_tracing(
            service_name=f"{settings.otel_service_name}-worker-{settings.worker_role}",
            otlp_endpoint=settings.otel_exporter_otlp_endpoint,
            enabled=True,
        )
    worker = AgentWorker()
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
