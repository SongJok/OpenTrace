"""
工作流引擎 — 具名、可复用的多步骤工作流。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from execution.dag_engine.engine import DAGEngine, Task
from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


@dataclass
class WorkflowStep:
    step_id: str
    name: str
    fn: Callable[[Task, dict[str, Any]], Awaitable[Any]]
    deps: list[str] = field(default_factory=list)
    timeout: float = 30.0


@dataclass
class WorkflowDefinition:
    workflow_id: str
    name: str
    description: str
    steps: list[WorkflowStep]


@dataclass
class WorkflowResult:
    workflow_id: str
    success: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class WorkflowEngine:
    """
    Executes named workflow definitions as DAGs.
    Register workflows once at startup, run them by ID.
    """

    def __init__(self) -> None:
        self._engine = DAGEngine()
        self._registry: dict[str, WorkflowDefinition] = {}

    def register(self, wf: WorkflowDefinition) -> None:
        self._registry[wf.workflow_id] = wf
        logger.info("Workflow registered", id=wf.workflow_id, name=wf.name)

    def list_workflows(self) -> list[str]:
        return list(self._registry.keys())

    async def run(
        self,
        workflow_id: str,
        context: Optional[dict[str, Any]] = None,
    ) -> WorkflowResult:
        with tracer.start_as_current_span("workflow_engine.run") as span:
            span.set_attribute("workflow.id", workflow_id)

            wf = self._registry.get(workflow_id)
            if wf is None:
                return WorkflowResult(
                    workflow_id=workflow_id,
                    success=False,
                    error=f"Workflow '{workflow_id}' not found",
                )

            tasks = [
                Task(
                    task_id=step.step_id,
                    fn=step.fn,
                    deps=step.deps,
                    task_type=step.name,
                    timeout=step.timeout,
                )
                for step in wf.steps
            ]

            try:
                outputs = await self._engine.execute(tasks, context=context)
                logger.info("Workflow completed", id=workflow_id)
                return WorkflowResult(
                    workflow_id=workflow_id,
                    success=True,
                    outputs=outputs,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Workflow failed", id=workflow_id, error=str(exc))
                return WorkflowResult(
                    workflow_id=workflow_id,
                    success=False,
                    error=str(exc),
                )


# Module-level singleton
workflow_engine = WorkflowEngine()
