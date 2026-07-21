"""
Resource-Aware Scheduler — CPU / GPU / IO slot management + priority.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from execution.dag_engine.graph import ResourceType, Task
from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


@dataclass
class ResourceLimits:
    cpu: int = 8
    gpu: int = 2
    io: int = 16

    def get(self, resource: ResourceType) -> int:
        return {ResourceType.CPU: self.cpu, ResourceType.GPU: self.gpu, ResourceType.IO: self.io}[resource]


class ResourceScheduler:
    """
    Tracks available resource slots.
    schedule() selects tasks that fit within current limits,
    sorted by descending priority.
    Release slots via release() after task completion.
    """

    def __init__(self, limits: ResourceLimits | None = None) -> None:
        self._limits = limits or ResourceLimits()
        self._current: dict[ResourceType, int] = {
            ResourceType.CPU: 0,
            ResourceType.GPU: 0,
            ResourceType.IO: 0,
        }
        self._lock = asyncio.Lock()

    async def acquire(self, task: Task) -> bool:
        """Try to acquire a slot for task. Returns True if granted."""
        async with self._lock:
            rt = task.resource
            if self._current[rt] < self._limits.get(rt):
                self._current[rt] += 1
                return True
            return False

    async def release(self, task: Task) -> None:
        async with self._lock:
            rt = task.resource
            if self._current[rt] > 0:
                self._current[rt] -= 1

    def schedule(self, ready_tasks: list[Task]) -> list[Task]:
        """
        Synchronously select schedulable tasks from ready list.
        Sorted by priority (higher = first). Does NOT acquire slots —
        caller must call acquire() before executing.
        """
        sorted_tasks = sorted(ready_tasks, key=lambda t: -t.priority)
        selected: list[Task] = []
        for task in sorted_tasks:
            rt = task.resource
            projected = self._current[rt] + len([s for s in selected if s.resource == rt])
            if projected < self._limits.get(rt):
                selected.append(task)
        return selected

    def utilization(self) -> dict[str, str]:
        return {
            rt.value: f"{self._current[rt]}/{self._limits.get(rt)}"
            for rt in ResourceType
        }
