from __future__ import annotations

import asyncio
import uuid

from agents.base import AgentResult, TaskMessage
from agents.registry import AgentRegistry
from infra.config.settings import settings
from infra.message_bus.agent_bus import AgentMessageBus, AgentTaskEnvelope
from kernel.dag_plan import DagNode, DagPlan
from kernel.dag_scheduler import DagScheduler
from kernel.plan_agent import TaskPlan, SubTask


class RuntimeSupervisor:
    """Lightweight runtime validator for agent results."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def check(self, result: AgentResult) -> tuple[bool, str]:
        if not self.enabled:
            return True, "disabled"
        if result.status == "timeout":
            return False, "timeout"
        if result.status == "error":
            return False, "agent_error"

        if result.agent_type == "data":
            if not isinstance(result.metadata, dict):
                return False, "data_metadata_missing"
            row_count = int(result.metadata.get("row_count", 0) or 0)
            if row_count <= 0:
                return False, "data_empty_rows"

        if result.agent_type == "web":
            text = (result.content or "").strip()
            if len(text) < 20:
                return False, "web_content_too_short"

        if result.agent_type == "rag":
            chunks = result.metadata.get("chunks") if isinstance(result.metadata, dict) else None
            if not isinstance(chunks, list) or len(chunks) == 0:
                return False, "rag_chunks_empty"

        if result.agent_type == "skills":
            meta = result.metadata if isinstance(result.metadata, dict) else {}
            matched = int(meta.get("matched_skills", 0) or 0)
            installed = int(meta.get("installed_count", 0) or 0)
            if installed > 0 and matched == 0:
                return False, "skills_no_match"
            text = (result.content or "").strip()
            if len(text) < 10:
                return False, "skills_content_too_short"

        return True, "ok"


class Dispatcher:
    def __init__(
        self,
        registry: AgentRegistry,
        timeout_sec: int = 30,
        bus_enabled: bool = False,
        bus_namespace: str = "opentrace:agent",
        max_retry: int | None = None,
        runtime_supervisor_enabled: bool | None = None,
    ) -> None:
        self.registry = registry
        self.timeout_sec = timeout_sec
        self.bus_enabled = bus_enabled
        self.bus = AgentMessageBus(namespace=bus_namespace)
        self.max_retry = int(settings.kernel_agent_max_retry if max_retry is None else max_retry)
        enabled = settings.kernel_agent_runtime_supervisor_enabled if runtime_supervisor_enabled is None else runtime_supervisor_enabled
        self.supervisor = RuntimeSupervisor(enabled=bool(enabled))

    async def dispatch(self, plan: TaskPlan, event_cb=None) -> list[AgentResult]:
        if bool(settings.kernel_agent_dag_scheduling_enabled) and any(getattr(s, "depends_on", []) for s in plan.subtasks):
            dag_nodes = [
                DagNode(
                    node_id=getattr(st, "params", {}).get("node_id") or f"node_{idx}_{st.agent_type}",
                    agent_type=st.agent_type,
                    query=st.query,
                    params={**(st.params or {}), "session_id": (st.params or {}).get("session_id", ""), "user_id": (st.params or {}).get("user_id", "")},
                    depends_on=list(getattr(st, "depends_on", []) or []),
                )
                for idx, st in enumerate(plan.subtasks)
            ]
            dag_result = await DagScheduler(self.registry, timeout_sec=self.timeout_sec).execute(DagPlan(nodes=dag_nodes, speculative_execution=bool(settings.kernel_agent_speculative_execution_enabled)), event_cb=event_cb)
            return dag_result.results

        return await self._execute_parallel(plan.subtasks)

    async def _execute_parallel(self, subtasks: list[SubTask]) -> list[AgentResult]:
        high_priority_tasks = [st for st in subtasks if getattr(st, "priority", "normal") == "high"]
        normal_tasks = [st for st in subtasks if getattr(st, "priority", "normal") != "high"]
        results: list[AgentResult] = []

        if high_priority_tasks:
            high_results = await asyncio.gather(*[self._run_one(asyncio.Semaphore(1), st) for st in high_priority_tasks], return_exceptions=True)
            for st, res in zip(high_priority_tasks, high_results):
                agent_result = self._coerce_result(res, st.agent_type)
                results.append(agent_result)
                if st.agent_type == "rag" and not self._is_rag_quality_sufficient(agent_result, st):
                    fallback_to_web = bool((st.params or {}).get("fallback_to_web", False))
                    if fallback_to_web:
                        normal_tasks.append(
                            SubTask(
                                agent_type="web",
                                query=st.query,
                                params={"fallback_reason": "rag_insufficient", "fallback_source_task": st.params.get("node_id", "")},
                            )
                        )

        if normal_tasks:
            sem = asyncio.Semaphore(max(1, len(normal_tasks), 1))
            normal_raw = await asyncio.gather(*[self._run_one(sem, st) for st in normal_tasks], return_exceptions=True)
            for st, res in zip(normal_tasks, normal_raw):
                results.append(self._coerce_result(res, st.agent_type))

        return results

    def _coerce_result(self, raw: AgentResult | Exception | object, agent_type: str) -> AgentResult:
        if isinstance(raw, AgentResult):
            return raw
        if isinstance(raw, Exception):
            return AgentResult(task_id=str(uuid.uuid4()), agent_type=agent_type, status="error", content="", error=str(raw))
        return AgentResult(task_id=str(uuid.uuid4()), agent_type=agent_type, status="error", content="", error="invalid result")

    def _is_rag_quality_sufficient(self, result: AgentResult, task: SubTask) -> bool:
        chunks = result.metadata.get("chunks", []) if isinstance(result.metadata, dict) else []
        if not chunks:
            return False
        avg_score = sum(float(c.get("score", 0) or 0.0) for c in chunks) / len(chunks)
        min_threshold = float((task.params or {}).get("min_evidence_score", 0.5) or 0.5)
        return avg_score >= min_threshold

    async def _run_one(self, sem: asyncio.Semaphore, subtask: SubTask) -> AgentResult:
        async with sem:
            last_result: AgentResult | None = None
            for attempt in range(self.max_retry + 1):
                result = await self._execute_once(subtask=subtask, attempt=attempt)
                ok, reason = self.supervisor.check(result)
                if ok:
                    if attempt > 0:
                        result.metadata = {
                            **(result.metadata or {}),
                            "runtime_supervisor": {
                                "recovered_after_retry": True,
                                "attempt": attempt,
                            },
                        }
                    return result

                result.metadata = {
                    **(result.metadata or {}),
                    "runtime_supervisor": {
                        "passed": False,
                        "reason": reason,
                        "attempt": attempt,
                    },
                }
                last_result = result
                if attempt < self.max_retry:
                    await asyncio.sleep(0.15 * (2**attempt))

            return last_result or AgentResult(
                task_id=str(uuid.uuid4()),
                agent_type=subtask.agent_type,
                status="error",
                content="",
                error="runtime supervisor rejected result",
            )

    async def _execute_once(self, subtask: SubTask, attempt: int) -> AgentResult:
        params = dict(subtask.params or {})
        params["attempt"] = attempt
        msg = TaskMessage(
            task_id=str(uuid.uuid4()),
            agent_type=subtask.agent_type,
            query=subtask.query,
            params=params,
            session_id=str(params.get("session_id", "") or "") or None,
            user_id=str(params.get("user_id", "") or "") or None,
        )
        if self.bus_enabled:
            await self.bus.publish_task(
                AgentTaskEnvelope(
                    task_id=msg.task_id,
                    agent_type=subtask.agent_type,
                    query=subtask.query,
                    params=params,
                    session_id=str(params.get("session_id", "") or ""),
                    user_id=str(params.get("user_id", "") or ""),
                    attempt=int(params.get("attempt", 0) or 0),
                )
            )
            try:
                data = await self.bus.wait_for_result(msg.task_id, timeout_sec=self.timeout_sec)
                return AgentResult(
                    task_id=msg.task_id,
                    agent_type=subtask.agent_type,
                    status=str(data.get("status", "error")),
                    content=str(data.get("content", "")),
                    confidence=float(data.get("confidence", 0.0) or 0.0),
                    metadata=data.get("metadata") or {},
                    error=data.get("error"),
                )
            except asyncio.TimeoutError:
                # If the message bus worker is unavailable, degrade to in-process execution
                # so RAG/Text2SQL do not silently fail into web-only answers.
                if bool(getattr(settings, "kernel_agent_bus_require_worker", False)):
                    return AgentResult(task_id=msg.task_id, agent_type=subtask.agent_type, status="timeout", content="", error="timeout")
                pass

        agent = self.registry.get_agent(subtask.agent_type)
        try:
            return await asyncio.wait_for(agent.execute(msg), timeout=self.timeout_sec)
        except asyncio.TimeoutError:
            return AgentResult(task_id=msg.task_id, agent_type=subtask.agent_type, status="timeout", content="", error="timeout")
