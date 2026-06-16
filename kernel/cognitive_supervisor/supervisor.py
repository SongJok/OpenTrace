"""
认知监督层 — GoalGraph、治理、多问与运行时策略。

位于 CognitiveKernel 与 RuntimeGateway 之间。RuntimeGateway 仅负责：
  查找运行时 → 调度 → 返回符合 Artifact 契约的结果。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger
from kernel.protocol.runtime_contract import RuntimeTask

logger = get_logger(__name__)


@dataclass
class SupervisorPreparedRun:
    """Everything RuntimeGateway needs after supervisor preparation."""

    runtime_task: RuntimeTask
    ctx: Any
    route_hint: str = "cognitive_executive"
    multi_question_result: Any | None = None
    governance_meta: dict[str, Any] = field(default_factory=dict)
    semantic_observability: dict[str, Any] = field(default_factory=dict)
    goal_graph_dict: dict[str, Any] = field(default_factory=dict)


class CognitiveSupervisor:
    """
    Owns: GoalGraph materialization, intent stabilization hooks, runtime policy,
    governance pre-check, multi-question path, budget/strategy projection metadata.
    """

    def prepare_run(self, request: Any) -> SupervisorPreparedRun:
        from kernel.cognitive_supervisor.prepare_dispatch import (
            build_runtime_context_from_kernel_request,
            runtime_task_from_request,
            runtime_task_from_request_light,
        )
        from kernel.cognitive_supervisor.control_plane_gate import evaluate_request_control_plane
        from kernel.governance.runtime_policy_engine import RuntimePolicyEngine
        from kernel.governance.runtime_governor import RuntimeGovernor

        t0 = time.monotonic()
        cp_decision = evaluate_request_control_plane(request)
        if not cp_decision.get("allowed", True):
            return SupervisorPreparedRun(
                runtime_task=runtime_task_from_request_light(request),
                ctx=None,
                route_hint="control_plane_denied",
                governance_meta={
                    "allowed": False,
                    "violations": list(cp_decision.get("violations") or []),
                    "control_plane": cp_decision,
                },
            )
        lock = (request.metadata or {}).get("intent_lock") or {}
        complexity = str(lock.get("complexity_level") or "")
        slim = complexity in ("L0", "L1") and not (request.metadata or {}).get("force_mode")
        runtime_task = (
            runtime_task_from_request_light(request)
            if slim
            else runtime_task_from_request(request)
        )
        sub_count = (
            max(0, len(runtime_task.goal_graph.goals) - 1)
            if runtime_task.goal_graph
            else 0
        )
        policy = RuntimePolicyEngine().evaluate_planning_phase(
            runtime_task, sub_goal_count=sub_count
        )
        if not policy.allowed:
            from kernel.goal.goal_recovery import mark_goals_blocked_for_governance

            mark_goals_blocked_for_governance(
                runtime_task.goal_graph, violations=list(policy.violations)
            )
            return SupervisorPreparedRun(
                runtime_task=runtime_task,
                ctx=None,
                route_hint="runtime_policy_denied",
                governance_meta={"violations": policy.violations, "allowed": False},
            )
        gov = RuntimeGovernor().evaluate_task(runtime_task)
        if not gov.allowed:
            from kernel.goal.goal_recovery import mark_goals_blocked_for_governance

            mark_goals_blocked_for_governance(
                runtime_task.goal_graph, violations=list(gov.violations)
            )
            return SupervisorPreparedRun(
                runtime_task=runtime_task,
                ctx=None,
                route_hint="runtime_governance_denied",
                governance_meta={"violations": gov.violations, "allowed": False},
            )

        ctx = build_runtime_context_from_kernel_request(request)
        if ctx.metadata is None:
            ctx.metadata = {}
        try:
            from kernel.turn_enrichment import sync_enrichment_metadata_to_runtime_context

            sync_enrichment_metadata_to_runtime_context(ctx, request)
        except Exception as exc:
            logger.debug("supervisor_enrichment_sync_skipped", error=str(exc))
        self._hydrate_world_state_if_enabled(request, ctx)
        ctx.metadata["runtime_task"] = runtime_task
        goal_dict = (
            runtime_task.goal_graph.to_dict() if runtime_task.goal_graph else {}
        )
        ctx.metadata["goal_graph"] = goal_dict

        from kernel.goal.goal_lifecycle import bind_goal_graph_to_context

        bind_goal_graph_to_context(ctx, runtime_task)

        from kernel.goal.goal_projection import project_goal_graph_to_world_state

        world = project_goal_graph_to_world_state(runtime_task.goal_graph)
        ctx.metadata["goal_world_projection"] = world
        request.metadata = dict(request.metadata or {})
        request.metadata["goal_world_projection"] = world

        memory_context = request.metadata.get("memory_context") or []
        if memory_context and not getattr(ctx, "memory_context", None):
            ctx.memory_context = "\n".join(
                m.get("content", "") for m in memory_context[:8]
            )

        self._apply_runtime_policy(request, runtime_task, ctx)
        self._inject_strategy_projection(request, runtime_task)
        self._seed_context_fabric(request, runtime_task, ctx)
        try:
            from kernel.agent_runtime.world_decision_runtime import enrich_world_projection_for_turn

            bundle = enrich_world_projection_for_turn(
                ctx,
                query=str(getattr(request, "query", "") or ""),
                goal_description=str(
                    (runtime_task.goal_graph.protected_intent if runtime_task.goal_graph else "")
                    or getattr(request, "query", "")
                    or ""
                ),
            )
            request.metadata = dict(request.metadata or {})
            request.metadata.update(bundle.to_metadata_dict())
        except Exception as exc:
            from infra.observability.runtime_degraded import record_degradation_in_context

            record_degradation_in_context(
                ctx, subsystem="world_decision_runtime", detail="prepare_run", exc=exc
            )

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        sem_obs = {
            "supervisor_prepare_ms": elapsed_ms,
            "goal_count": len(runtime_task.goal_graph.goals)
            if runtime_task.goal_graph
            else 1,
            "intent_category": (
                runtime_task.goal_graph.intent_category
                if runtime_task.goal_graph
                else "general"
            ),
        }

        try:
            from infra.config.flag_governance import export_effective_runtime_flags
            from infra.config.settings import settings

            ctx.metadata["effective_runtime_flags"] = export_effective_runtime_flags(settings)
        except Exception as exc:
            from infra.observability.runtime_degraded import record_degradation_in_context

            record_degradation_in_context(
                ctx, subsystem="flag_governance", detail="effective_runtime_flags", exc=exc
            )

        gov_meta: dict[str, Any] = {"allowed": True, "violations": []}
        try:
            gov_meta["control_plane"] = cp_decision
        except Exception as exc:
            from infra.observability.runtime_degraded import record_degradation_in_context

            record_degradation_in_context(
                ctx, subsystem="control_plane", detail="attach_cp_decision", exc=exc
            )
        prepared = SupervisorPreparedRun(
            runtime_task=runtime_task,
            ctx=ctx,
            route_hint="cognitive_executive",
            governance_meta=gov_meta,
            semantic_observability=sem_obs,
            goal_graph_dict=goal_dict,
        )
        from kernel.cognitive_supervisor.dispatch_enrichment import apply_dispatch_enrichment

        apply_dispatch_enrichment(request, prepared)
        return prepared

    def _hydrate_world_state_if_enabled(self, request: Any, ctx: Any) -> None:
        """Restore persisted world state (in-process store; async Redis hydrate when safe)."""
        try:
            from infra.config.settings import settings

            if not bool(getattr(settings, "kernel_world_state_persist_enabled", False)):
                return
            sid = str(getattr(ctx, "session_id", "") or getattr(request, "session_id", "") or "")
            if not sid:
                return
            from kernel.cognition.runtime_grounding import (
                get_grounding,
                hydrate_world_state_for_session,
            )

            import asyncio

            # Same-worker sessions already retain state in get_grounding(sid).
            prior = get_grounding(sid)
            if prior.world_state_id:
                ctx.metadata = ctx.metadata or {}
                ctx.metadata["world_state_hydrated"] = {
                    "source": "in_process",
                    "world_state_id": prior.world_state_id,
                    "turn_index": prior.turn_index,
                }
                return

            try:
                asyncio.get_running_loop()

                async def _bg() -> None:
                    persisted = await hydrate_world_state_for_session(sid)
                    if persisted and ctx.metadata is not None:
                        ctx.metadata.setdefault("world_state_hydrated_async", persisted)

                asyncio.create_task(_bg())
            except RuntimeError:
                persisted = asyncio.run(hydrate_world_state_for_session(sid))
                if persisted:
                    ctx.metadata = ctx.metadata or {}
                    ctx.metadata["world_state_hydrated"] = {
                        "source": "redis",
                        "world_state_id": persisted.get("world_state_id"),
                        "turn_index": persisted.get("turn_index"),
                    }
        except Exception as exc:
            from infra.observability.runtime_degraded import record_degradation_in_context

            record_degradation_in_context(
                ctx, subsystem="world_state", detail="hydrate_world_state", exc=exc
            )

    def _apply_runtime_policy(
        self, request: Any, task: RuntimeTask, ctx: Any
    ) -> None:
        """Budget projection and capability allowlists on context."""
        lock = request.metadata.get("intent_lock") or {}
        budget = lock.get("cognitive_budget") or {}
        if budget:
            ctx.metadata["cognitive_budget_projection"] = dict(budget)
        if task.constraints.allowed_capabilities:
            ctx.metadata["allowed_capabilities"] = list(
                task.constraints.allowed_capabilities
            )

    def _inject_strategy_projection(
        self, request: Any, task: RuntimeTask
    ) -> None:
        """Lightweight strategic hints for ExecutionPlanner (not planning itself)."""
        from kernel.cognition.planner_facade import get_strategic_planner

        hints = get_strategic_planner().project_hints(task, request)
        try:
            from kernel.capability_intelligence.strategy_pattern import (
                planner_enabled,
                top_k_patterns_for_planner,
            )

            if planner_enabled():
                intent = hints.get("intent_category") or "general"
                allowed = list(task.constraints.allowed_capabilities or [])
                hints["strategy_patterns"] = top_k_patterns_for_planner(
                    intent, capabilities=allowed, k=3
                )
        except Exception as exc:
            logger.debug("strategy_pattern_projection_skipped", error=str(exc))
        request.metadata = dict(request.metadata or {})
        request.metadata["strategy_projection"] = hints

    def _seed_context_fabric(
        self, request: Any, task: RuntimeTask, ctx: Any
    ) -> None:
        """Seed session fabric graph at prepare time (goal + intent)."""
        try:
            from kernel.context_fabric import get_context_fabric

            sid = str(getattr(ctx, "session_id", "") or request.session_id or "")
            root = ""
            if task.goal_graph:
                root = task.goal_graph.root_goal_id
            elif task.goal:
                root = task.goal.goal_id
            graph_dict = get_context_fabric().evolve_runtime(
                sid,
                goal_id=root,
                runtime_phase="prepare",
            )
            ctx.metadata = ctx.metadata or {}
            ctx.metadata["fabric_graph_seeded"] = graph_dict
            request.metadata = dict(request.metadata or {})
            request.metadata["fabric_graph_seeded"] = graph_dict
        except Exception as exc:
            from infra.observability.runtime_degraded import record_degradation_in_context

            record_degradation_in_context(
                ctx, subsystem="context_fabric", detail="seed_fabric_graph", exc=exc
            )


def get_cognitive_supervisor() -> CognitiveSupervisor:
    if not hasattr(get_cognitive_supervisor, "_instance"):
        get_cognitive_supervisor._instance = CognitiveSupervisor()  # type: ignore[attr-defined]
    return get_cognitive_supervisor._instance  # type: ignore[attr-defined]