"""
AgentRuntime — orchestrates Planner -> DAGEngine -> Executor -> Critic -> Reflector.
Exposes both run(RuntimeRequest) and execute(plan) interfaces.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from agent_runtime.critic.critic import Critic
from agent_runtime.executor.executor import Executor
from agent_runtime.planner.planner import Plan, Planner, SubTask
from agent_runtime.reflector.reflector import Reflector
from execution.dag_engine.engine import DAGEngine, Task
from infra.observability.logger import get_logger
from infra.observability.metrics import AGENT_TASKS_TOTAL
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


@dataclass
class RuntimeRequest:
    query: str
    session_id: str = ""
    context: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeResult:
    run_id: str
    goal: str
    final_answer: str
    subtask_results: dict[str, Any]
    reflection: Optional[Any] = None
    passed_critic: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentRuntime:
    """
    Full multi-agent pipeline:
      1. Planner   — decompose goal -> SubTask DAG
      2. DAGEngine — parallel execution respecting deps
      3. Executor  — tool-first, LLM fallback per subtask
      4. Critic    — validate aggregated answer
      5. Reflector — extract lessons (fire-and-forget)

    Two entry points:
      run(RuntimeRequest)  — used by CognitiveOrchestrator (MULTI_AGENT route)
      execute(plan)        — used when a plan is pre-built externally
    """

    def __init__(
        self,
        planner: Optional[Planner] = None,
        executor: Optional[Executor] = None,
        critic: Optional[Critic] = None,
        reflector: Optional[Reflector] = None,
    ) -> None:
        self.planner = planner or Planner()
        self.executor = executor or Executor()
        self.critic = critic or Critic()
        self.reflector = reflector or Reflector()
        self._dag_engine = DAGEngine()

    # ------------------------------------------------------------------
    # Primary interface — used by CognitiveOrchestrator
    # ------------------------------------------------------------------
    async def run(self, request: RuntimeRequest) -> RuntimeResult:
        run_id = str(uuid.uuid4())[:12]
        with tracer.start_as_current_span("agent_runtime.run") as span:
            span.set_attribute("run.id", run_id)
            AGENT_TASKS_TOTAL.labels(agent_type="runtime", status="started").inc()
            logger.info("AgentRuntime.run", run_id=run_id, query=request.query[:80])

            plan = await self.planner.create_plan(
                goal=request.query, context=request.context
            )
            return await self._run_plan(run_id, plan, request.query)

    # ------------------------------------------------------------------
    # Secondary interface — accepts a pre-built plan dict
    # ------------------------------------------------------------------
    async def execute(self, plan: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a pre-built plan dict produced by CognitiveOrchestrator or Planner.
        Accepts: {"tasks": [{"id": str, "type": str, "description": str, "depends_on": [...]}]}
        Returns: {task_id: result, ...}
        """
        run_id = str(uuid.uuid4())[:12]
        tasks_raw = plan.get("tasks", [])
        subtasks = [
            SubTask(
                task_id=t.get("id", f"t{i}"),
                description=t.get("description", t.get("type", "task")),
                deps=t.get("depends_on", t.get("deps", [])),
            )
            for i, t in enumerate(tasks_raw)
        ]
        built_plan = Plan(goal="", subtasks=subtasks)
        result = await self._run_plan(run_id, built_plan, "")
        return result.subtask_results

    # ------------------------------------------------------------------
    # Internal shared pipeline
    # ------------------------------------------------------------------
    async def _run_plan(
        self, run_id: str, plan: Plan, goal: str
    ) -> RuntimeResult:
        ctx: dict[str, Any] = {"plan": plan, "run_id": run_id}
        dag_tasks = self._build_dag_tasks(plan)

        subtask_results = await self._dag_engine.execute(dag_tasks, context=ctx)
        final_answer = self._aggregate(plan, subtask_results)

        critic_result = await self.critic.critique(task=goal or "task", output=final_answer)

        reflection = None
        try:
            reflection = await self.reflector.reflect(
                task=goal or "task",
                steps=[str(subtask_results.get(st.task_id, "")) for st in plan.subtasks],
                result=final_answer,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Reflection failed", error=str(exc))

        status = "success" if critic_result.ok else "low_quality"
        AGENT_TASKS_TOTAL.labels(agent_type="runtime", status=status).inc()
        logger.info("AgentRuntime complete", run_id=run_id, critic_ok=critic_result.ok)

        return RuntimeResult(
            run_id=run_id,
            goal=goal,
            final_answer=final_answer,
            subtask_results=subtask_results,
            reflection=reflection,
            passed_critic=critic_result.ok,
            metadata={"critic_score": critic_result.score},
        )

    def _build_dag_tasks(self, plan: Plan) -> list[Task]:
        tasks: list[Task] = []
        for st in plan.subtasks:
            _st = st  # closure capture

            async def _fn(task: Task, ctx: dict[str, Any], _s: SubTask = _st) -> str:
                return await self.executor.execute(_s, ctx)

            tasks.append(Task(
                task_id=st.task_id, fn=_fn, deps=st.deps,
                task_type="subtask", timeout=60.0,
            ))
        return tasks

    def _aggregate(self, plan: Plan, results: dict[str, Any]) -> str:
        parts = [
            f"[{st.description}]\n{results[st.task_id]}"
            for st in plan.subtasks
            if results.get(st.task_id)
        ]
        return "\n\n".join(parts) if parts else "No results produced."
