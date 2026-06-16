"""多问运行时 V2（GoalGraph + ExecutionPlanner P2 + 序列融合）。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from infra.config.settings import settings
from infra.observability.logger import get_logger
from kernel.cognition.multi_question import decompose_query, is_multi_question
from kernel.fusion_engine.sequence_fusion import SequenceFusionEngine
from kernel.fusion_engine.sequence_models import SequenceFusionInput

logger = get_logger(__name__)


@dataclass
class MultiQuestionRuntimeResult:
    content: str
    route: str = "multi_question_runtime_v2"
    validation_score: float = 0.85
    passed_validation: bool = True
    hallucination_risk: float = 0.0
    intent_category: str = "multi_question"
    total_latency_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    result_refs: list[dict[str, Any]] = field(default_factory=list)
    state_patch: dict[str, Any] | None = None


async def run_multi_question(request: Any, event_cb: Any = None) -> MultiQuestionRuntimeResult | None:
    """Decompose → ExecutionPlanner per sub-goal → ExecutionRuntime → SequenceFusion."""
    if not bool(getattr(settings, "kernel_multi_question_runtime_v2_enabled", True)):
        return None
    if not is_multi_question(request.query):
        return None

    t0 = time.monotonic()
    sub_questions = await decompose_query(request.query)
    if not sub_questions or len(sub_questions) < 2:
        return None

    from kernel.runtime_gateway import runtime_task_from_request

    request.metadata = dict(request.metadata or {})
    request.metadata["decomposed_goals"] = sub_questions
    request.metadata["is_multi_question"] = True
    runtime_task = runtime_task_from_request(request)
    goal_graph = runtime_task.goal_graph

    from kernel.goal.multi_goal_scheduler import (
        annotate_goal_lifecycle_for_subgoals,
        apply_goal_dependencies_to_execution_graph,
        schedule_sub_goals_from_graph,
    )

    if goal_graph:
        annotate_goal_lifecycle_for_subgoals(goal_graph)
        sub_questions = schedule_sub_goals_from_graph(goal_graph, sub_questions)
        request.metadata["decomposed_goals"] = sub_questions
        try:
            from kernel.goal.multi_goal_resources import project_multi_goal_resource_plan

            lock = (request.metadata or {}).get("intent_lock") or {}
            budget = lock.get("cognitive_budget") or {}
            resource_plan = project_multi_goal_resource_plan(
                goal_graph, cognitive_budget=budget
            )
            request.metadata["multi_goal_resource_plan"] = resource_plan
            sequential = bool(resource_plan.get("sequential_required"))
        except Exception as exc:
            logger.debug("multi_goal_resource_plan_skipped", error=str(exc))
            sequential = bool(
                getattr(settings, "kernel_multi_goal_sequential_enabled", True)
            )
    else:
        sequential = bool(
            getattr(settings, "kernel_multi_goal_sequential_enabled", True)
        )

    from kernel.cognition.multi_execution_planner import build_multi_execution_graph
    from kernel.runtime.capability import capability_registry
    from kernel.runtime.executor import ExecutionRuntime
    from kernel.runtime_gateway import build_runtime_context_from_kernel_request

    execution_graph, _node_meta = await build_multi_execution_graph(request, sub_questions)
    if not execution_graph:
        return None

    execution_graph = apply_goal_dependencies_to_execution_graph(
        execution_graph, sequential_sub_goals=sequential
    )

    ctx = build_runtime_context_from_kernel_request(request)
    runtime = ExecutionRuntime(
        capability_registry=capability_registry,
        timeout_sec=int(getattr(settings, "kernel_agent_timeout_sec", 30) or 30),
        max_parallel=int(getattr(settings, "kernel_agent_max_parallel", 5) or 5),
    )
    agent_results = await runtime.execute(
        plan=None,
        ctx=ctx,
        event_cb=event_cb,
        capability_executor_mode=bool(
            getattr(settings, "kernel_agent_capability_executor_mode", True)
        ),
        execution_graph=execution_graph,
    )

    try:
        from kernel.goal.goal_execution_outcomes import record_goal_execution_outcomes

        record_goal_execution_outcomes(ctx, execution_graph, agent_results)
        request.metadata = dict(request.metadata or {})
        request.metadata["goal_execution_outcomes"] = (ctx.metadata or {}).get(
            "goal_execution_outcomes"
        )
    except Exception as exc:
        logger.debug("multi_question_goal_outcomes_skipped", error=str(exc))

    try:
        from kernel.capability_runtime.dispatch_pipeline import (
            collect_executed_capability_types,
            record_capability_outcomes,
        )

        record_capability_outcomes(agent_results, query_preview=str(request.query or "")[:80])
        caps = collect_executed_capability_types(agent_results)
        if caps:
            ctx.metadata = ctx.metadata or {}
            ctx.metadata["capabilities_used"] = caps
            ctx.metadata.setdefault("capability_type", caps[0])
            request.metadata = dict(request.metadata or {})
            request.metadata["capabilities_used"] = caps
    except Exception as exc:
        logger.debug("multi_question_capability_outcomes_skipped", error=str(exc))

    for i, r in enumerate(agent_results):
        md = dict(getattr(r, "metadata", None) or {})
        if i < len(execution_graph):
            params = getattr(execution_graph[i], "params", None) or {}
            if params.get("sub_question_id"):
                md["sub_question_id"] = params["sub_question_id"]
                md["display_order"] = params.get("display_order", i + 1)
        r.metadata = md

    attachment_contexts = request.metadata.get("attachment_contexts", [])
    background = ""
    if attachment_contexts:
        bg_parts = [
            str(ac["content"])
            for ac in attachment_contexts
            if isinstance(ac, dict) and ac.get("content")
        ]
        background = "\n\n---\n\n".join(bg_parts) if bg_parts else ""

    fusion_output = await SequenceFusionEngine().run(
        SequenceFusionInput(
            query=request.query,
            sub_questions=sub_questions,
            agent_results=agent_results,
            background_materials=background,
        )
    )
    answer = (fusion_output.content or "").strip()
    if not answer:
        answer = "抱歉，暂时无法生成完整的回答。请尝试逐个提问，或提供更详细的信息。"

    from kernel.governance.governance_center import get_governance_center

    mcg = (request.metadata or {}).get("multi_capability_governance") or {}
    cap_denied = len(mcg.get("denied") or [])
    gov = get_governance_center().evaluate_turn(
        evidence_count=sum(
            1 for r in agent_results if getattr(r, "status", "") != "error"
        ),
        fusion_confidence=float(fusion_output.confidence or 0.85),
        hallucination_risk=0.0,
        critic_passed=True,
        route="multi_question_runtime_v2",
        min_evidence=len(sub_questions),
        sub_goal_count=max(0, len(sub_questions)),
        replanned=cap_denied > 0,
    )

    total_ms = int((time.monotonic() - t0) * 1000)
    state_patch = {
        "is_multi_question": True,
        "sub_question_count": len(sub_questions),
        "goal_graph": goal_graph.to_dict() if goal_graph else {},
    }
    meta = {
        "multi_question": True,
        "planner": "execution_planner_v2_p2",
        "sub_questions": sub_questions,
        "goal_graph": goal_graph.to_dict() if goal_graph else {},
        "execution_node_count": len(execution_graph),
        "multi_capability_governance": mcg,
        "semantic_observability": gov.semantic_observability,
        "governance": {"evidence": gov.evidence, "risk": gov.risk},
        "per_question_results": [
            {
                "sub_question_id": p.sub_question_id,
                "question_text": p.question_text,
                "success": p.success,
            }
            for p in fusion_output.per_question_results
        ],
    }
    if request.metadata.get("force_mode"):
        meta["force_mode"] = request.metadata.get("force_mode")
    caps = (request.metadata or {}).get("capabilities_used") or (ctx.metadata or {}).get(
        "capabilities_used"
    )
    if caps:
        meta["capabilities_used"] = list(caps)
    caps = list((request.metadata or {}).get("capabilities_used") or [])
    if caps:
        meta["capabilities_used"] = caps

    sub_goal_bindings = []
    goal_evolution: dict[str, Any] = {}
    try:
        from kernel.goal.multi_goal_outcomes import (
            build_sub_goal_bindings,
            evolve_sub_goals_after_multi_execution,
        )

        sub_goal_bindings = build_sub_goal_bindings(execution_graph, sub_questions)
        meta["sub_goal_bindings"] = sub_goal_bindings
        goal_evolution = evolve_sub_goals_after_multi_execution(
            goal_graph,
            session_id=str(request.session_id or ""),
            request_id=str(request.metadata.get("request_id", request.session_id or "")),
            execution_graph=execution_graph,
            agent_results=agent_results,
            sub_goal_bindings=sub_goal_bindings,
        )
        meta["goal_evolution"] = goal_evolution
    except Exception as exc:
        logger.debug("multi_goal_outcomes skipped", error=str(exc))

    try:
        from kernel.goal.goal_evidence_binding import extract_evidence_ids
        from kernel.protocol.behavior_contracts import ReplayContract, validate_replay_contract

        root_id = str(
            (goal_graph.root_goal_id if goal_graph else "")
            or (request.metadata or {}).get("request_id", "")
        )
        req_id = str((request.metadata or {}).get("request_id", request.session_id or ""))
        evidence_ids: list[str] = []
        for r in agent_results:
            if hasattr(r, "evidence_objects") and r.evidence_objects:
                evidence_ids.extend(extract_evidence_ids(r.evidence_objects))
        replay = ReplayContract(
            request_id=req_id,
            session_id=str(request.session_id or ""),
            root_goal_id=root_id,
            artifact_id=f"multi:{req_id}",
            evidence_ids=evidence_ids,
        )
        violations = validate_replay_contract(replay)
        meta["replay_contract"] = {
            "request_id": replay.request_id,
            "session_id": replay.session_id,
            "root_goal_id": replay.root_goal_id,
            "artifact_id": replay.artifact_id,
            "evidence_ids": replay.evidence_ids,
            "valid": len(violations) == 0,
            "violations": violations,
        }
    except Exception as exc:
        logger.debug("multi_question_replay_contract_skipped", error=str(exc))

    try:
        from kernel.goal.goal_memory_binding import bind_goal_turn_to_memory_fabric

        bind_goal_turn_to_memory_fabric(
            session_id=str(request.session_id or ""),
            request_id=str(request.metadata.get("request_id", request.session_id or "")),
            goal_id=str((goal_graph.to_dict() if goal_graph else {}).get("root_goal_id", "")),
            route="multi_question_runtime_v2",
            query_preview=str(request.query or "")[:120],
            answer_preview=answer[:200],
        )
    except Exception as exc:
        logger.debug("multi_question_goal_memory_binding_skipped", error=str(exc))

    return MultiQuestionRuntimeResult(
        content=answer,
        validation_score=float(fusion_output.confidence or 0.85),
        total_latency_ms=total_ms,
        metadata=meta,
        result_refs=list(fusion_output.result_refs or []),
        state_patch=state_patch,
    )