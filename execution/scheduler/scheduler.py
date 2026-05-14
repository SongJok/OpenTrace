"""
Task Scheduler — priority queue using the new DAGEngine.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional

from execution.dag_engine.engine import DAGEngine
from execution.dag_engine.graph import ResourceType, Task
from execution.dag_engine.scheduler import ResourceLimits
from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


class Priority(IntEnum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


@dataclass(order=True)
class ScheduledJob:
    priority: Priority
    job_id: str = field(compare=False)
    tasks: list[Task] = field(compare=False, default_factory=list)
    context: dict[str, Any] = field(compare=False, default_factory=dict)
    result: Optional[dict[str, Any]] = field(compare=False, default=None)


class TaskScheduler:
    """
    Priority-ordered job queue backed by the cognitive DAGEngine.
    Exposes submit() / execute_now() / start() / stop().
    """

    def __init__(
        self,
        max_concurrent: int = 4,
        resource_limits: Optional[ResourceLimits] = None,
    ) -> None:
        self._queue: asyncio.PriorityQueue[ScheduledJob] = asyncio.PriorityQueue()
        self._engine = DAGEngine(
            limits=resource_limits or ResourceLimits(cpu=max_concurrent),
            checkpoint=False,
        )
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None

    async def submit(
        self,
        tasks: list[Task],
        priority: Priority = Priority.NORMAL,
        context: Optional[dict[str, Any]] = None,
        job_id: str = "",
    ) -> str:
        jid = job_id or str(uuid.uuid4())
        job = ScheduledJob(
            priority=priority, job_id=jid,
            tasks=tasks, context=context or {},
        )
        await self._queue.put(job)
        logger.info("Job enqueued", job_id=jid, priority=priority.name)
        return jid

    async def execute_now(
        self,
        tasks: list[Task],
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Bypass queue — execute immediately."""
        async with self._semaphore:
            return await self._engine.execute(tasks, context=context)

    async def start(self) -> None:
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("TaskScheduler started")

    async def stop(self) -> None:
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
        logger.info("TaskScheduler stopped")

    async def _worker(self) -> None:
        while self._running:
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                asyncio.create_task(self._run_job(job))
            except asyncio.TimeoutError:
                continue
            except Exception as exc:  # noqa: BLE001
                logger.error("Scheduler worker error", error=str(exc))

    async def _run_job(self, job: ScheduledJob) -> None:
        with tracer.start_as_current_span("scheduler.run_job") as span:
            span.set_attribute("job.id", job.job_id)
            span.set_attribute("job.priority", job.priority.name)
            async with self._semaphore:
                try:
                    job.result = await self._engine.execute(
                        job.tasks, context=job.context
                    )
                    logger.info("Job completed", job_id=job.job_id)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Job failed", job_id=job.job_id, error=str(exc))
                finally:
                    self._queue.task_done()


from infra.config.settings import settings

scheduler = TaskScheduler(
    max_concurrent=int(getattr(settings, "kernel_agent_max_parallel", 4))
)
