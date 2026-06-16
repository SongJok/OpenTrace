"""
认知 DAG 引擎 — 执行层核心。

能力：
  1. 动态 DAG — 运行时可派生子任务
  2. 异步并行 — 按并发层级 asyncio.gather
  3. 资源感知 — 经 Scheduler 限制 CPU/GPU/IO 槽位
  4. 重试与回滚 — 按任务重试，可配置回滚
  5. 检查点 — StateManager 持久化以恢复
  6. 多 Agent 节点 — 任务函数可为 agent/tool/model
  7. 可观测 — 每任务 OTel span + Prometheus 指标
  8. 事件总线 — 任务生命周期事件供外部订阅
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

import networkx as nx

from infra.observability.logger import get_logger
from infra.observability.metrics import DAG_EXECUTIONS_TOTAL, DAG_TASK_DURATION
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    RETRYING = "RETRYING"


class ResourceType(str, Enum):
    CPU = "CPU"
    GPU = "GPU"
    IO = "IO"


class NodeType(str, Enum):
    GENERIC = "generic"
    REASONING = "reasoning"
    TOOL = "tool"
    AGENT = "agent"
    MODEL = "model"


# ---------------------------------------------------------------------------
# Task dataclass
# ---------------------------------------------------------------------------
@dataclass
class Task:
    """
    Cognitive execution node — can be reasoning / tool / agent / model.
    """
    task_id: str
    fn: Callable[["Task", dict[str, Any]], Awaitable[Any]]
    deps: list[str] = field(default_factory=list)

    # Execution control
    retries: int = 2
    timeout: float = 30.0
    priority: int = 0          # higher = scheduled first

    # Resource constraint
    resource: ResourceType = ResourceType.CPU

    # Cognitive node type (for observability + routing)
    node_type: NodeType = NodeType.GENERIC
    task_type: str = "generic"  # backwards-compat alias

    # Dynamic DAG — if True, fn may return list[Task] to inject new tasks
    dynamic: bool = False

    # Rollback hook — called if task fails after all retries
    rollback_fn: Optional[Callable[["Task", dict[str, Any]], Awaitable[None]]] = None

    # Runtime state
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[Exception] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    attempt: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed(self) -> float:
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return 0.0


# ---------------------------------------------------------------------------
# DAG Graph
# ---------------------------------------------------------------------------
class DAGGraph:
    """
    Mutable directed acyclic graph supporting dynamic task injection.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._g: nx.DiGraph = nx.DiGraph()

    def add_task(self, task: Task) -> None:
        self._tasks[task.task_id] = task
        self._g.add_node(task.task_id)
        for dep in task.deps:
            self._g.add_edge(dep, task.task_id)
        if not nx.is_directed_acyclic_graph(self._g):
            # Roll back the addition
            self._g.remove_node(task.task_id)
            del self._tasks[task.task_id]
            raise ValueError(f"Adding task '{task.task_id}' would create a cycle")

    def get_ready(self, completed: set[str]) -> list[Task]:
        """Return PENDING tasks whose all deps are completed."""
        return [
            t for t in self._tasks.values()
            if t.status == TaskStatus.PENDING
            and all(dep in completed for dep in t.deps)
        ]

    def all_done(self, completed: set[str], failed: set[str]) -> bool:
        for t in self._tasks.values():
            if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.RETRYING):
                return False
        return True

    @property
    def tasks(self) -> dict[str, Task]:
        return self._tasks

    def from_task_list(self, tasks: list[Task]) -> "DAGGraph":
        for t in tasks:
            self.add_task(t)
        return self

    @classmethod
    def from_task_plan(
        cls,
        plan: Any,  # TaskPlan
        capability_registry: Any = None,
        ctx: Any = None,  # RuntimeContext
        timeout_sec: float = 30.0,
    ) -> "DAGGraph":
        """Factory: build a DAGGraph from a planner TaskPlan.

        Converts each SubTask into a DAG Task whose fn is an agent executor.
        Dependencies are resolved from SubTask.depends_on → Task.deps.
        """
        from agents.base import AgentResult
        from kernel.agent_runtime.dag_invoke import invoke_dag_agent

        graph = cls()

        for idx, st in enumerate(plan.subtasks):
            task_id = getattr(st, "sub_question_id", None) or f"task_{idx}_{st.agent_type}"

            async def _agent_fn(
                task: Task,
                meta: dict,
                _agent_type: str = st.agent_type,
                _query: str = st.query,
                _params: dict = dict(st.params or {}),
            ) -> AgentResult:
                return await invoke_dag_agent(
                    task_id=task.task_id,
                    agent_type=_agent_type,
                    query=_query,
                    params=_params,
                    capability_registry=capability_registry,
                    ctx=ctx,
                    timeout_sec=timeout_sec,
                )

            task = Task(
                task_id=task_id,
                fn=_agent_fn,
                deps=list(getattr(st, "depends_on", []) or []),
                timeout=timeout_sec,
                priority={"high": 2, "normal": 1, "low": 0}.get(
                    getattr(st, "priority", "normal") or "normal", 1
                ),
                node_type=NodeType.AGENT,
                task_type=st.agent_type,
                metadata={
                    "agent_type": st.agent_type,
                    "query": st.query,
                    "params": dict(st.params or {}),
                    "display_order": getattr(st, "display_order", idx),
                },
            )
            graph.add_task(task)

        return graph

    @classmethod
    def from_execution_graph(
        cls,
        nodes: list,  # list[ExecutionNode]
        capability_registry: Any = None,
        ctx: Any = None,  # RuntimeContext
        timeout_sec: float = 30.0,
        capability_executor_mode: bool = False,
    ) -> "DAGGraph":
        """Factory: build a DAGGraph from ExecutionNode list.

        Each ExecutionNode is converted to a Task that calls the agent
        via execute_as_capability() when capability_executor_mode is enabled,
        or via the legacy execute() otherwise.
        """
        from agents.base import AgentResult
        from kernel.agent_runtime.dag_invoke import invoke_dag_agent

        graph = cls()

        for node in nodes:
            agent_type = _capability_to_agent(node.capability_name)
            cap_name = node.capability_name
            node_query = node.query
            node_params = dict(node.params or {})
            exec_type = getattr(node, "executor_type", "") or ""

            if agent_type == "__model__" or cap_name == "model.answer" or exec_type == "model":
                async def _model_node(
                    task: Task,
                    meta: dict,
                    _query: str = node_query,
                ) -> AgentResult:
                    from model.model_gateway.gateway import LLMMessage, LLMRole, get_model_gateway

                    try:
                        gw = get_model_gateway()
                        resp = await asyncio.wait_for(
                            gw.complete(
                                [LLMMessage(role="user", content=_query or "")],
                                role=LLMRole.QUERY,
                                temperature=0.3,
                                max_tokens=1024,
                            ),
                            timeout=timeout_sec,
                        )
                        text = (resp.content or "").strip()
                        return AgentResult(
                            task_id=task.task_id,
                            agent_type="model",
                            status="success",
                            content=text,
                            confidence=0.85,
                        )
                    except Exception as exc:
                        return AgentResult(
                            task_id=task.task_id,
                            agent_type="model",
                            status="error",
                            content="",
                            error=str(exc),
                        )

                task = Task(
                    task_id=node.node_id,
                    fn=_model_node,
                    deps=list(node.depends_on),
                    timeout=timeout_sec,
                    priority={"high": 2, "normal": 1, "low": 0}.get(node.priority, 1),
                    node_type=NodeType.MODEL,
                    task_type="model.answer",
                    metadata={
                        "capability_name": cap_name,
                        "executor_type": "model",
                        "query": node_query,
                    },
                )
                graph.add_task(task)
                continue

            async def _exec_node(
                task: Task,
                meta: dict,
                _agent_type: str = agent_type,
                _query: str = node_query,
                _params: dict = node_params,
                _cap_name: str = cap_name,
            ) -> AgentResult:
                return await invoke_dag_agent(
                    task_id=task.task_id,
                    agent_type=_agent_type,
                    query=_query,
                    params=_params,
                    capability_registry=capability_registry,
                    ctx=ctx,
                    timeout_sec=timeout_sec,
                    capability_executor_mode=capability_executor_mode,
                    capability_name=_cap_name,
                )

            task = Task(
                task_id=node.node_id,
                fn=_exec_node,
                deps=list(node.depends_on),
                timeout=timeout_sec,
                priority={"high": 2, "normal": 1, "low": 0}.get(node.priority, 1),
                node_type=NodeType.AGENT,
                task_type=agent_type,
                metadata={
                    "capability_name": node.capability_name,
                    "executor_type": node.executor_type,
                    "query": node.query,
                    "params": dict(node.params or {}),
                    "resource": node.resource,
                },
            )
            graph.add_task(task)

        return graph


def _capability_to_agent(capability_type: str) -> str:
    """Map capability_type → legacy agent_type for executor lookup."""
    key = (capability_type or "").strip().lower()
    mapping = {
        "data.query": "data",
        "data.analysis": "data",
        "web.search": "web",
        "rag.retrieve": "rag",
        "tool.datetime": "tool",
        "tool.weather": "tool",
        "tool.calculator": "tool",
        "python.execute": "tool",
        "python": "tool",
        "chart.generate": "tool",
        "memory.retrieve": "rag",
        "skill.invoke": "skills",
        "rule.lookup": "rule_engine",
        "vision.analyze": "vision",
        "entity.resolution": "data",
        "model.answer": "__model__",
    }
    if key in mapping:
        return mapping[key]
    if key == "python":
        return "tool"
    if key == "model":
        return "__model__"
    if "." in key:
        head = key.split(".")[0]
        if head == "python":
            return "tool"
        if head == "model":
            return "__model__"
        return head
    return key
