"""
Cognitive Execution Engine — world-class DAG engine.

Upgrades over the original:
  - Dynamic DAG: tasks can inject new tasks at runtime
  - Resource-aware: CPU/GPU/IO slot limits via ResourceScheduler
  - Retry + rollback: per-task retry counter + rollback_fn hook
  - Checkpoint: auto-save every N completions, resume from Redis
  - EventBus: lifecycle events for external subscribers
  - Cognitive nodes: fn can be reasoning / tool / agent / model
  - Backwards-compatible: old Task dataclass still accepted
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional

from execution.dag_engine.events import EventBus, event_bus as _default_bus
from execution.dag_engine.graph import DAGGraph, NodeType, ResourceType, Task, TaskStatus
from execution.dag_engine.scheduler import ResourceLimits, ResourceScheduler
from execution.dag_engine.state import StateManager, state_manager as _default_state
from infra.observability.logger import get_logger
from infra.observability.metrics import DAG_EXECUTIONS_TOTAL, DAG_TASK_DURATION
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)

_CHECKPOINT_INTERVAL = 5  # save state every N completed tasks


class DAGEngine:
    """
    Cognitive Execution Engine.

    Usage (backwards-compat)::

        engine = DAGEngine()
        results = await engine.execute(tasks, context={...})

    Usage (full)::

        engine = DAGEngine(
            limits=ResourceLimits(cpu=8, gpu=2, io=16),
            checkpoint=True,
        )
        results = await engine.run(dag_graph, dag_id="my-dag", context={...})
    """

    def __init__(
        self,
        limits: Optional[ResourceLimits] = None,
        event_bus: Optional[EventBus] = None,
        state_manager: Optional[StateManager] = None,
        checkpoint: bool = False,
    ) -> None:
        self._scheduler = ResourceScheduler(limits or ResourceLimits())
        self._bus = event_bus or _default_bus
        self._state = state_manager or _default_state
        self._checkpoint = checkpoint

    # ------------------------------------------------------------------
    # Primary API — full DAGGraph interface
    # ------------------------------------------------------------------
    async def run(
        self,
        dag: DAGGraph,
        dag_id: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        """
        Execute a DAGGraph with full cognitive engine features.
        Set resume=True to load checkpoint from Redis before starting.
        """
        did = dag_id or str(uuid.uuid4())[:12]
        ctx = context or {}
        completed: set[str] = set()
        results: dict[str, Any] = {}
        failed: set[str] = set()

        with tracer.start_as_current_span("dag_engine.run") as span:
            span.set_attribute("dag.id", did)
            span.set_attribute("dag.tasks.total", len(dag.tasks))

            # Resume from checkpoint
            if resume:
                cp = await self._state.load(did)
                if cp:
                    completed, results = self._state.restore_task_statuses(dag.tasks, cp)
                    logger.info("DAG resumed from checkpoint", dag_id=did,
                                completed=len(completed))

            await self._bus.publish("dag.started", {
                "dag_id": did, "task_count": len(dag.tasks)
            })

            t0 = time.monotonic()
            n_completed = 0

            while True:
                ready = dag.get_ready(completed)
                if not ready and dag.all_done(completed, failed):
                    break
                if not ready:
                    await asyncio.sleep(0.05)  # wait for running tasks
                    continue

                # Schedule by resource + priority
                scheduled = self._scheduler.schedule(ready)
                if not scheduled:
                    await asyncio.sleep(0.05)
                    continue

                # Acquire slots + launch concurrently
                granted: list[Task] = []
                for task in scheduled:
                    if await self._scheduler.acquire(task):
                        granted.append(task)

                await asyncio.gather(
                    *[self._execute_task(task, dag, results, ctx, did, completed, failed)
                      for task in granted]
                )

                # Update completion tracking
                for task in granted:
                    if task.status == TaskStatus.SUCCESS:
                        completed.add(task.task_id)
                        n_completed += 1
                    elif task.status == TaskStatus.FAILED:
                        failed.add(task.task_id)
                        n_completed += 1

                # Periodic checkpoint
                if self._checkpoint and n_completed % _CHECKPOINT_INTERVAL == 0:
                    asyncio.create_task(
                        self._state.save(did, dag.tasks, results, completed)
                    )

            elapsed = time.monotonic() - t0
            success_n = sum(1 for t in dag.tasks.values() if t.status == TaskStatus.SUCCESS)
            fail_n = sum(1 for t in dag.tasks.values() if t.status == TaskStatus.FAILED)

            span.set_attribute("dag.tasks.success", success_n)
            span.set_attribute("dag.tasks.failed", fail_n)
            DAG_EXECUTIONS_TOTAL.labels(
                status="success" if fail_n == 0 else "partial_failure"
            ).inc()

            await self._bus.publish("dag.completed", {
                "dag_id": did, "success": success_n,
                "failed": fail_n, "elapsed": elapsed,
            })

            if self._checkpoint:
                await self._state.delete(did)

            logger.info("DAG complete", dag_id=did, success=success_n,
                        failed=fail_n, elapsed_s=round(elapsed, 2))
            return results

    # ------------------------------------------------------------------
    # Backwards-compat API — accepts list[Task]
    # ------------------------------------------------------------------
    async def execute(
        self,
        tasks: list[Task],
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Original interface — converts list to DAGGraph and runs."""
        dag = DAGGraph()
        for t in tasks:
            # Normalize legacy Task fields
            if not hasattr(t, "resource"):
                t.resource = ResourceType.CPU  # type: ignore[attr-defined]
            dag.add_task(t)
        return await self.run(dag, context=context)

    # ------------------------------------------------------------------
    # Task execution
    # ------------------------------------------------------------------
    async def _execute_task(
        self,
        task: Task,
        dag: DAGGraph,
        results: dict[str, Any],
        ctx: dict[str, Any],
        dag_id: str,
        completed: set[str],
        failed: set[str],
    ) -> None:
        # Skip if any dep failed
        for dep in task.deps:
            if dep in failed or results.get(f"__err_{dep}"):
                task.status = TaskStatus.SKIPPED
                await self._bus.publish("task.skipped", {
                    "dag_id": dag_id, "task_id": task.task_id, "dep": dep
                })
                await self._scheduler.release(task)
                return

        task.status = TaskStatus.RUNNING
        task.started_at = time.monotonic()
        task.attempt += 1

        await self._bus.publish("task.started", {
            "dag_id": dag_id, "task_id": task.task_id,
            "node_type": task.node_type.value,
        })

        try:
            result = await asyncio.wait_for(
                task.fn(task, ctx), timeout=task.timeout
            )

            task.result = result
            task.status = TaskStatus.SUCCESS
            results[task.task_id] = result

            # Dynamic DAG injection
            if task.dynamic and isinstance(result, list):
                new_tasks = [t for t in result if isinstance(t, Task)]
                for nt in new_tasks:
                    try:
                        dag.add_task(nt)
                    except ValueError as e:
                        logger.warning("Dynamic task rejected", error=str(e))
                if new_tasks:
                    await self._bus.publish("task.dynamic", {
                        "dag_id": dag_id, "task_id": task.task_id,
                        "new_tasks": [t.task_id for t in new_tasks],
                    })

            await self._bus.publish("task.succeeded", {
                "dag_id": dag_id, "task_id": task.task_id, "elapsed": task.elapsed
            })

        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
            task.error = exc

            if task.retries > 0 and task.attempt <= task.retries + 1:
                task.retries -= 1
                task.status = TaskStatus.RETRYING
                backoff = min(2 ** task.attempt, 30)
                logger.warning("Task retrying", task=task.task_id,
                               attempt=task.attempt, backoff=backoff)
                await self._bus.publish("task.retrying", {
                    "dag_id": dag_id, "task_id": task.task_id,
                    "attempt": task.attempt, "max_retries": task.retries,
                })
                await asyncio.sleep(backoff)
                # Re-queue by resetting to PENDING so the engine picks it up
                task.status = TaskStatus.PENDING
                task.retries_remaining = task.retries  # type: ignore[attr-defined]
            else:
                task.status = TaskStatus.FAILED
                results[f"__err_{task.task_id}"] = exc
                logger.error("Task failed", task=task.task_id,
                             error=str(exc), attempts=task.attempt)
                await self._bus.publish("task.failed", {
                    "dag_id": dag_id, "task_id": task.task_id,
                    "error": str(exc), "attempt": task.attempt,
                })
                # Rollback hook
                if task.rollback_fn:
                    try:
                        await task.rollback_fn(task, ctx)
                        logger.info("Rollback executed", task=task.task_id)
                    except Exception as rb_exc:  # noqa: BLE001
                        logger.error("Rollback failed", task=task.task_id, error=str(rb_exc))

        finally:
            task.finished_at = time.monotonic()
            if task.started_at:
                DAG_TASK_DURATION.labels(
                    task_type=task.task_type or task.node_type.value
                ).observe(task.elapsed)
            await self._scheduler.release(task)
