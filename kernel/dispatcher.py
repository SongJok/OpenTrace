"""
[已弃用] Dispatcher + RuntimeSupervisor — 重试/降级任务分发。

已被 kernel.runtime.executor.ExecutionRuntime（认知运行时 Phase 3）取代。
Agent 自主降级/重试在 capability_executor_mode 下已禁用。
移除目标：v6.0。
"""

from __future__ import annotations

import asyncio
import uuid

from agents.base import AgentResult, TaskMessage
from agents.registry import AgentRegistry
from infra.config.settings import settings
from infra.message_bus.agent_bus import AgentMessageBus, AgentTaskEnvelope
from kernel.dag_plan import DagNode, DagPlan
from kernel.dag_scheduler import DagScheduler
from kernel.plan_agent import SubTask, TaskPlan


class RuntimeSupervisor:
    """轻量级运行时验证器，用于验证 Agent 结果。"""

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
        max_parallel: int = 5,
        execution_runtime: Any = None,  # ExecutionRuntime | None
    ) -> None:
        self.registry = registry
        self.timeout_sec = timeout_sec
        self.bus_enabled = bus_enabled
        self.bus = AgentMessageBus(namespace=bus_namespace)
        self.max_retry = int(settings.kernel_agent_max_retry if max_retry is None else max_retry)
        enabled = (
            settings.kernel_agent_runtime_supervisor_enabled
            if runtime_supervisor_enabled is None
            else runtime_supervisor_enabled
        )
        self.supervisor = RuntimeSupervisor(enabled=bool(enabled))
        self.max_parallel = max_parallel
        self.execution_runtime = execution_runtime

    async def dispatch(
        self,
        plan: TaskPlan,
        event_cb=None,
        previous_results: list[AgentResult] | None = None,
        ctx: Any = None,  # RuntimeContext
    ) -> list[AgentResult]:
        # 当 ExecutionRuntime 可用时委托给它（Phase 1.4 路径）
        if self.execution_runtime is not None:
            return await self.execution_runtime.execute(plan, ctx=ctx, event_cb=event_cb)
        # ── 特性⑥：DAG 检查点复用 ──────────────────────────
        # 如果提供了 previous_results（来自对话分支），
        # 跳过 query + agent_type 匹配已有结果的子任务。
        prev_map: dict[tuple[str, str], AgentResult] = {}
        if previous_results:
            for pr in previous_results:
                key = (pr.agent_type, (pr.metadata or {}).get("query", "") or "")
                prev_map[key] = pr

        if previous_results:
            new_subtasks: list[SubTask] = []
            reused_results: list[AgentResult] = []
            for st in plan.subtasks:
                match_key = (st.agent_type, st.query)
                if match_key in prev_map:
                    reused = prev_map[match_key]
                    reused.metadata = {
                        **(reused.metadata or {}),
                        "reused_from_checkpoint": True,
                    }
                    reused_results.append(reused)
                else:
                    new_subtasks.append(st)
            if reused_results and not new_subtasks:
                return reused_results
            if reused_results:
                plan.subtasks = new_subtasks
                remaining = await self._dispatch_inner(plan, event_cb)
                return reused_results + remaining
        # ── DAG 检查点复用结束 ─────────────────────────────────

        return await self._dispatch_inner(plan, event_cb)

    async def _dispatch_inner(self, plan: TaskPlan, event_cb=None) -> list[AgentResult]:
        if bool(settings.kernel_agent_dag_scheduling_enabled) and any(
            getattr(s, "depends_on", []) for s in plan.subtasks
        ):
            dag_nodes = [
                DagNode(
                    node_id=getattr(st, "params", {}).get("node_id")
                    or f"node_{idx}_{st.agent_type}",
                    agent_type=st.agent_type,
                    query=st.query,
                    params={
                        **(st.params or {}),
                        "session_id": (st.params or {}).get("session_id", ""),
                        "user_id": (st.params or {}).get("user_id", ""),
                    },
                    depends_on=list(getattr(st, "depends_on", []) or []),
                )
                for idx, st in enumerate(plan.subtasks)
            ]
            dag_result = await DagScheduler(
                self.registry,
                timeout_sec=self.timeout_sec,
                max_parallel=self.max_parallel,
            ).execute(
                DagPlan(
                    nodes=dag_nodes,
                    speculative_execution=bool(settings.kernel_agent_speculative_execution_enabled),
                ),
                event_cb=event_cb,
            )
            return dag_result.results

        return await self._execute_parallel(plan.subtasks)

    async def _execute_parallel(self, subtasks: list[SubTask]) -> list[AgentResult]:
        high_priority_tasks = [st for st in subtasks if getattr(st, "priority", "normal") == "high"]
        normal_tasks = [st for st in subtasks if getattr(st, "priority", "normal") != "high"]
        results: list[AgentResult] = []

        if high_priority_tasks:
            high_sem = asyncio.Semaphore(self.max_parallel)
            high_results = await asyncio.gather(
                *[self._run_one(high_sem, st) for st in high_priority_tasks],
                return_exceptions=True,
            )
            for st, res in zip(high_priority_tasks, high_results):
                results.append(self._coerce_result(res, st.agent_type))

        if normal_tasks:
            sem = asyncio.Semaphore(self.max_parallel)
            normal_raw = await asyncio.gather(
                *[self._run_one(sem, st) for st in normal_tasks], return_exceptions=True
            )
            for st, res in zip(normal_tasks, normal_raw):
                results.append(self._coerce_result(res, st.agent_type))

        return results

    def _coerce_result(self, raw: AgentResult | Exception | object, agent_type: str) -> AgentResult:
        if isinstance(raw, AgentResult):
            return raw
        if isinstance(raw, Exception):
            return AgentResult(
                task_id=str(uuid.uuid4()),
                agent_type=agent_type,
                status="error",
                content="",
                error=str(raw),
            )
        return AgentResult(
            task_id=str(uuid.uuid4()),
            agent_type=agent_type,
            status="error",
            content="",
            error="invalid result",
        )

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
            from kernel.agent_runtime.manifest import get_manifest

            get_manifest().assert_bus_routing(subtask.agent_type)
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
            except TimeoutError:
                # 如果消息总线 worker 不可用，降级为进程内执行
                # 以避免 RAG/Text2SQL 静默降级为仅 web 回答。
                if bool(getattr(settings, "kernel_agent_bus_require_worker", False)):
                    return AgentResult(
                        task_id=msg.task_id,
                        agent_type=subtask.agent_type,
                        status="timeout",
                        content="",
                        error="timeout",
                    )
                pass

        agent = self.registry.get_agent(subtask.agent_type)
        try:
            return await asyncio.wait_for(agent.execute(msg), timeout=self.timeout_sec)
        except TimeoutError:
            return AgentResult(
                task_id=msg.task_id,
                agent_type=subtask.agent_type,
                status="timeout",
                content="",
                error="timeout",
            )
