"""
Cognitive DAG Engine — world-class execution engine.

Capabilities:
  1. Dynamic DAG  — tasks can spawn new tasks at runtime
  2. Async Parallel — asyncio.gather per concurrent level
  3. Resource-aware — CPU / GPU / IO slot limits via Scheduler
  4. Retry + Rollback — per-task retries with configurable rollback
  5. Checkpoint — StateManager persistence for resume
  6. Multi-Agent nodes — any task fn can be an agent / tool / model
  7. Observability — OTel spans + Prometheus metrics per task
  8. EventBus — task lifecycle events for external subscribers
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
