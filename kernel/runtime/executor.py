"""
ExecutionRuntime — 基于 DAG 的任务执行统一层。

收敛了此前分裂的执行路径：
  - kernel/dag_scheduler.py  → 简单 DAG 调度器（已弃用）
  - execution/dag_engine/     → 完整 DAG 引擎（现为主路径）
  - kernel/dispatcher.py      → RAG→web 回退逻辑（已移除）

ExecutionRuntime 接收 TaskPlan，通过 DAG 引擎执行所有子任务，
遵循依赖关系、优先级和并行度限制。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents.base import AgentResult

from execution.dag_engine.graph import DAGGraph, Task, TaskStatus
from infra.observability.logger import get_logger

logger = get_logger(__name__)


class ExecutionRuntime:
    """统一执行层。

    接收计划并执行——不做质量检查、不做回退逻辑、不做自动注入。
    那些属于编排器的职责。
    """

    def __init__(
        self,
        capability_registry: Any = None,  # CapabilityRegistry
        timeout_sec: int = 30,
        max_parallel: int = 5,
    ) -> None:
        self.capability_registry = capability_registry
        self.timeout_sec = timeout_sec
        self.max_parallel = max_parallel

    async def execute(
        self,
        plan: Any,  # TaskPlan | list[ExecutionNode]
        ctx: Any = None,  # RuntimeContext
        event_cb: Callable | None = None,
        capability_executor_mode: bool = False,
        execution_graph: list | None = None,  # list[ExecutionNode] — 优先的新路径
    ) -> list[AgentResult]:
        """通过 DAG 引擎执行计划。

        支持两条路径：
        - 旧路径：TaskPlan → DAGGraph.from_task_plan()
        - 新路径：ExecutionGraph (list[ExecutionNode]) → DAGGraph.from_execution_graph()

        Args:
            plan: TaskPlan（旧路径）— 当 execution_graph 为 None 时使用
            execution_graph: ExecutionNode 列表（新路径）— 优先使用
            capability_executor_mode: 启用 execute_as_capability() 路径
        """
        if execution_graph:
            graph = DAGGraph.from_execution_graph(
                execution_graph,
                capability_registry=self.capability_registry,
                ctx=ctx,
                timeout_sec=self.timeout_sec,
                capability_executor_mode=capability_executor_mode,
            )
        else:
            graph = DAGGraph.from_task_plan(
                plan,
                capability_registry=self.capability_registry,
                ctx=ctx,
                timeout_sec=self.timeout_sec,
            )
        return await _execute_graph(graph, self.max_parallel, event_cb)

    async def _handle_node_failure(
        self,
        task_id: str,
        error_msg: str,
        plan: Any,
        completed_results: list[Any],
        query: str,
        depth: int = 0,
    ) -> list[Any] | None:
        """对失败的 DAG 节点尝试有界局部重规划。

        仅重建下游子图。最多 2 层重规划。
        返回重建节点的新结果，若不可恢复则返回 None。
        """
        if depth >= 2:
            logger.warning("Max replanning depth reached", task_id=task_id)
            return None

        try:
            from kernel.refine_planner import RefinePlanner

            rp = RefinePlanner()
            intent = await rp.detect_correction(
                query=query,
                previous_plan=plan,
                failed_result=_error_result(task_id, "unknown", error_msg),
            )

            if not intent.is_correction:
                return None

            refined = rp.refine_plan(
                correction_intent=intent,
                previous_plan=plan,
                previous_results=completed_results,
                query=query,
                depth=depth,
            )

            if refined.repair_strategy == "retry":
                return None  # 调用方应重试同一节点

            logger.info(
                "Bounded replanning applied",
                strategy=refined.repair_strategy,
                depth=depth + 1,
                node_id=task_id,
            )
            return None  # 完整重规划路径待第二阶段实现
        except Exception as exc:
            logger.debug("Bounded replanning skipped", error=str(exc))
            return None


async def _execute_graph(
    graph: DAGGraph,
    max_parallel: int = 5,
    event_cb: Callable | None = None,
) -> list[Any]:
    """执行 DAG 图的任务，遵循依赖关系和并行度。

    节点失败时支持有界重规划：重试、跳过或中止分支。
    """
    from agents.base import AgentResult

    completed_ids: set[str] = set()
    failed_ids: set[str] = set()
    results: list[AgentResult] = []
    inflight: dict[str, asyncio.Task] = {}
    sem = asyncio.Semaphore(max_parallel)
    # 跟踪每个节点的失败次数，用于重试/重规划决策
    node_failure_counts: dict[str, int] = {}
    max_retries = 2

    async def _run_one(task: Task) -> AgentResult:
        async with sem:
            task.status = TaskStatus.RUNNING
            if event_cb:
                await event_cb({"type": "task_start", "task_id": task.task_id})

            try:
                result = await asyncio.wait_for(
                    task.fn(task, task.metadata),
                    timeout=task.timeout,
                )
                task.result = result
                task.status = TaskStatus.SUCCESS
            except TimeoutError:
                task.error = TimeoutError(f"Task {task.task_id} timed out")
                task.status = TaskStatus.FAILED
                result = _error_result(task.task_id, task.node_type.value if hasattr(task, 'node_type') else "unknown", "timeout")
            except Exception as exc:
                task.error = exc
                task.status = TaskStatus.FAILED
                result = _error_result(task.task_id, task.node_type.value if hasattr(task, 'node_type') else "unknown", str(exc))

            if event_cb:
                await event_cb({
                    "type": "task_complete",
                    "task_id": task.task_id,
                    "status": task.status.value,
                })

            return result

    while not graph.all_done(completed_ids, failed_ids):
        ready = graph.get_ready(completed_ids)

        # 启动所有就绪任务，不超过 max_parallel
        for task in ready:
            if len(inflight) >= max_parallel:
                break
            # 跳过已失败次数过多的任务
            if node_failure_counts.get(task.task_id, 0) >= max_retries:
                failed_ids.add(task.task_id)
                results.append(_error_result(task.task_id, "unknown", "max_retries_exceeded"))
                continue
            inflight[task.task_id] = asyncio.create_task(_run_one(task))

        if not inflight:
            break

        done, _ = await asyncio.wait(
            inflight.values(),
            return_when=asyncio.FIRST_COMPLETED,
        )

        for t in done:
            task_id = next((tid for tid, ct in inflight.items() if ct is t), None)
            if task_id is None:
                continue
            inflight.pop(task_id, None)

            result = await t
            if isinstance(result, AgentResult):
                results.append(result)
                if result.status == "success":
                    completed_ids.add(task_id)
                    node_failure_counts.pop(task_id, None)  # 成功后重置
                else:
                    # 有界重规划：记录失败，决定重试/跳过/中止
                    node_failure_counts[task_id] = node_failure_counts.get(task_id, 0) + 1
                    error_msg = getattr(result, "error", "") or "unknown error"

                    if node_failure_counts[task_id] <= 1:
                        # 首次失败 — 记录并允许重试
                        logger.debug(
                            "Task failed, will retry",
                            task_id=task_id,
                            error=error_msg[:100],
                        )
                    else:
                        # 反复失败 — 标记为永久失败
                        failed_ids.add(task_id)
                        logger.warning(
                            "Task permanently failed after retries",
                            task_id=task_id,
                            failures=node_failure_counts[task_id],
                            error=error_msg[:100],
                        )

                        # 记录到失败记忆
                        try:
                            from kernel.capability_intelligence.failure_memory import failure_memory
                            failure_memory.record_from_result(
                                capability_type=getattr(task, "node_type", "unknown"),
                                query=getattr(task, "task_type", ""),
                                success=False,
                                error_msg=error_msg,
                            )
                        except Exception as exc:
                            logger.debug("executor_failure_memory_skipped", error=str(exc))
            else:
                failed_ids.add(task_id)
                results.append(_error_result(task_id, "unknown", "non-agent-result"))

    return results


def _error_result(task_id: str, agent_type: str, error: str) -> Any:
    from agents.base import AgentResult

    return AgentResult(
        task_id=task_id,
        agent_type=agent_type,
        status="error",
        content="",
        error=error,
    )


def _make_agent_task_fn(
    agent_type: str,
    query: str,
    params: dict[str, Any],
    capability_registry: Any,
    timeout_sec: float,
) -> Callable:
    """从 agent 元数据构建适用于 DAG Task.fn 的可调用对象。"""

    async def _fn(task: Task, metadata: dict[str, Any]) -> Any:
        from agents.base import TaskMessage

        if capability_registry is not None:
            reg = capability_registry
        else:
            from agents.bootstrap import register_builtin_agents
            from kernel.runtime.capability import capability_registry as global_reg

            register_builtin_agents()
            reg = global_reg

        exec_agent = (
            reg.resolve_execution_agent(agent_type)
            if hasattr(reg, "resolve_execution_agent")
            else agent_type
        )
        try:
            agent = reg.get_agent(exec_agent)
        except KeyError:
            return _error_result(task.task_id, agent_type, f"agent not found: {agent_type}")

        msg = TaskMessage(
            task_id=task.task_id,
            agent_type=exec_agent,
            query=query,
            params=params,
            session_id=params.get("session_id"),
            user_id=params.get("user_id"),
        )

        try:
            return await asyncio.wait_for(agent.execute(msg), timeout=timeout_sec)
        except TimeoutError:
            return _error_result(task.task_id, agent_type, "timeout")

    return _fn
