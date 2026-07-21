"""自 RuntimeGateway 迁出的共享辅助函数 — 仅供 Supervisor 使用。"""

from __future__ import annotations

import uuid
from typing import Any

from infra.config.settings import settings
from kernel.protocol.runtime_contract import (
    Budget,
    Constraints,
    ExecutionPolicy,
    Goal,
    RuntimeContextRef,
    RuntimeTask,
)


def build_runtime_context_from_kernel_request(request: Any) -> Any:
    from kernel.runtime.context import RuntimeContext

    sid = request.session_id
    ctx = RuntimeContext(
        request_id=request.metadata.get("request_id", sid),
        session_id=sid,
        user_id=request.user_id,
        query=request.query,
        conversation_history=request.history,
        conversation_state=request.conversation_state,
        web_enabled=request.web_enabled,
        force_mode=request.metadata.get("force_mode", ""),
        data_source_context=request.metadata.get("data_source_context", {}),
        attachment_contexts=request.metadata.get("attachment_contexts", []),
        user_preferences=request.metadata.get("user_preferences", []),
        metadata=dict(request.metadata),
        trace_ctx=request.trace_ctx,
    )
    intent_lock_payload = request.metadata.get("intent_lock")
    if isinstance(intent_lock_payload, dict):
        ctx.raw_user_query = str(
            intent_lock_payload.get("raw_user_query") or request.query
        )
        ctx.protected_intent = str(
            intent_lock_payload.get("protected_intent") or request.query
        )
        ctx.task_type = str(intent_lock_payload.get("task_type") or "general_qa")
        ctx.allowed_capabilities = list(
            intent_lock_payload.get("allowed_capabilities") or []
        )
        ctx.disallowed_capabilities = list(
            intent_lock_payload.get("disallowed_capabilities") or []
        )
        ctx.intent_confidence = float(intent_lock_payload.get("confidence") or 0.0)
        ctx.cognitive_budget = dict(intent_lock_payload.get("cognitive_budget") or {})
        ctx.relevance_threshold = float(
            intent_lock_payload.get("relevance_threshold") or 0.35
        )
    ctx.turn_decision = dict(request.metadata.get("turn_decision") or {})
    pref_block = request.metadata.get("user_preference_context_block")
    if pref_block and not getattr(ctx, "preference_context_block", None):
        ctx.preference_context_block = str(pref_block)
    mem_ctx = request.metadata.get("memory_context")
    if mem_ctx and not getattr(ctx, "memory_context", None):
        if isinstance(mem_ctx, list):
            ctx.memory_context = "\n".join(
                str(m.get("content", ""))[:800]
                for m in mem_ctx[:8]
                if isinstance(m, dict)
            )
        else:
            ctx.memory_context = str(mem_ctx)
    return ctx


def runtime_task_from_request_light(request: Any) -> RuntimeTask:
    """Minimal GoalGraph for L0/L1 tool-style turns — skips heavy planner."""
    lock = request.metadata.get("intent_lock") or {}
    goal_id = str(request.metadata.get("request_id") or uuid.uuid4())
    root = Goal(goal_id=goal_id, description=request.query)
    budget_raw = lock.get("cognitive_budget") or {}
    constraints = Constraints(
        allowed_capabilities=list(lock.get("allowed_capabilities") or []),
        disallowed_capabilities=list(lock.get("disallowed_capabilities") or []),
        max_parallel=1,
        relevance_threshold=float(lock.get("relevance_threshold", 0.35) or 0.35),
    )
    from kernel.protocol.runtime_contract import GoalGraph

    graph = GoalGraph(
        root_goal_id=goal_id,
        goals=[root],
        intent_category=str(lock.get("task_type") or "tool"),
    )
    return RuntimeTask(
        id=goal_id,
        goal=root,
        goal_graph=graph,
        query=request.query,
        constraints=constraints,
        budget=Budget(
            max_steps=int(budget_raw.get("max_reasoning_steps", 2) or 2),
            max_replans=0,
        ),
        execution_policy=ExecutionPolicy(
            capability_executor_mode=True,
            timeout_sec=int(getattr(settings, "kernel_agent_timeout_sec", 30) or 30),
        ),
        context=RuntimeContextRef(
            request_id=goal_id,
            session_id=request.session_id,
            user_id=request.user_id,
            metadata={"intent_lock": lock, "goal_graph": graph.to_dict(), "light_prepare": True},
        ),
    )


def runtime_task_from_request(request: Any) -> RuntimeTask:
    from kernel.cognition.planner_facade import get_goal_planner

    lock = request.metadata.get("intent_lock") or {}
    goal_id = str(request.metadata.get("request_id") or uuid.uuid4())
    graph = get_goal_planner().build_from_request(request)
    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "kernel_goal_supervisor_enabled", True)):
            from kernel.goal.goal_supervisor import apply_goal_supervisor_to_request

            decision = apply_goal_supervisor_to_request(request, graph)
            graph = decision.graph
    except Exception as exc:
        from infra.observability.logger import get_logger
        from infra.observability.runtime_degraded import record_runtime_degradation

        get_logger(__name__).warning("goal_supervisor_apply_failed", error=str(exc))
        record_runtime_degradation(
            request.metadata if isinstance(getattr(request, "metadata", None), dict) else None,
            subsystem="goal_supervisor",
            detail="apply_goal_supervisor_to_request",
            exc=exc,
        )
    try:
        from kernel.goal.state_machine import initialize_graph_states

        initialize_graph_states(graph)
    except Exception as exc:
        from infra.observability.logger import get_logger
        from infra.observability.runtime_degraded import record_runtime_degradation

        get_logger(__name__).warning("initialize_graph_states_failed", error=str(exc))
        record_runtime_degradation(
            request.metadata if isinstance(getattr(request, "metadata", None), dict) else None,
            subsystem="goal_state_machine",
            detail="initialize_graph_states",
            exc=exc,
        )
    root = (
        graph.goals[0]
        if graph.goals
        else Goal(goal_id=goal_id, description=request.query)
    )
    budget_raw = lock.get("cognitive_budget") or {}
    constraints = Constraints(
        allowed_capabilities=list(lock.get("allowed_capabilities") or []),
        disallowed_capabilities=list(lock.get("disallowed_capabilities") or []),
        max_parallel=int(budget_raw.get("max_capabilities", 5) or 5),
        relevance_threshold=float(lock.get("relevance_threshold", 0.35) or 0.35),
    )
    return RuntimeTask(
        id=goal_id,
        goal=root,
        goal_graph=graph,
        query=request.query,
        constraints=constraints,
        budget=Budget(
            max_steps=int(budget_raw.get("max_reasoning_steps", 10) or 10),
            max_replans=int(budget_raw.get("max_replans", 1) or 1),
        ),
        execution_policy=ExecutionPolicy(
            capability_executor_mode=bool(
                getattr(settings, "kernel_agent_capability_executor_mode", True)
            ),
            timeout_sec=int(getattr(settings, "kernel_agent_timeout_sec", 30) or 30),
        ),
        context=RuntimeContextRef(
            request_id=goal_id,
            session_id=request.session_id,
            user_id=request.user_id,
            metadata={"intent_lock": lock, "goal_graph": graph.to_dict()},
        ),
    )
