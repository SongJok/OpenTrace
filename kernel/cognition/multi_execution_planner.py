"""P2：多问规划 — 经 ExecutionPlanner（不使用 PlanAgent.generate_multi_plan）。"""

from __future__ import annotations

import uuid
from typing import Any

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)

_DOMAIN_CAPABILITY: dict[str, str] = {
    "data_query": "data.query",
    "document_retrieval": "rag.retrieve",
    "web_search": "web.search",
    "tool_execution": "tool.datetime",
    "general_qa": "model.answer",
}

_FORCE_MODE_CAPABILITY: dict[str, str] = {
    "rag": "rag.retrieve",
    "data_query": "data.query",
    "data_analysis": "data.analysis",
    "web": "web.search",
    "tool": "tool.datetime",
    "skills": "skills.execute",
    "rule_engine": "skills.execute",
    "vision": "vision.analyze",
}


def _capability_allowed(cap: str, lock: dict[str, Any]) -> bool:
    allowed = lock.get("allowed_capabilities") or []
    disallowed = lock.get("disallowed_capabilities") or []
    if allowed and cap not in allowed and "model.answer" not in allowed:
        return cap in ("model.answer",)
    if cap in disallowed:
        return False
    return True


def _pick_capability_for_sub(sq: dict[str, str], force_mode: str, lock: dict[str, Any]) -> str:
    if force_mode and force_mode in _FORCE_MODE_CAPABILITY:
        return _FORCE_MODE_CAPABILITY[force_mode]
    domain = sq.get("domain", "general_qa")
    cap = _DOMAIN_CAPABILITY.get(domain, "model.answer")
    if not _capability_allowed(cap, lock):
        if _capability_allowed("model.answer", lock):
            return "model.answer"
        for fallback in ("rag.retrieve", "web.search", "data.query", "tool.datetime"):
            if _capability_allowed(fallback, lock):
                return fallback
    return cap


async def build_multi_execution_graph(
    request: Any,
    sub_questions: list[dict[str, str]],
) -> tuple[list[Any], list[dict[str, str]]]:
    """Plan each sub-question with ExecutionPlanner; merge ExecutionNodes."""
    from kernel.cognition.planner_facade import ExecutionPlanner
    from kernel.runtime.context import RuntimeContext
    from kernel.runtime_gateway import build_runtime_context_from_kernel_request

    base_ctx = build_runtime_context_from_kernel_request(request)
    lock = (request.metadata or {}).get("intent_lock") or {}
    force_mode = str((request.metadata or {}).get("force_mode") or "").strip()
    data_src = (request.metadata or {}).get("data_source_context") or {}
    ds_id = data_src.get("data_source_id", "")

    planner = ExecutionPlanner()
    merged_nodes: list[Any] = []
    node_meta: list[dict[str, str]] = []
    multi_gov_allowed: list[str] = []
    multi_gov_denied: list[str] = []

    for i, sq in enumerate(sub_questions):
        sq_id = sq.get("id", f"q{i+1}")
        text = (sq.get("text") or "").strip()
        if not text:
            continue

        ctx = RuntimeContext(
            request_id=f"{base_ctx.request_id}:{sq_id}",
            session_id=base_ctx.session_id,
            user_id=base_ctx.user_id,
            query=text,
            conversation_history=base_ctx.conversation_history,
            conversation_state=base_ctx.conversation_state,
            web_enabled=base_ctx.web_enabled,
            force_mode=base_ctx.force_mode,
            data_source_context=dict(base_ctx.data_source_context or {}),
            attachment_contexts=list(base_ctx.attachment_contexts or []),
            metadata=dict(base_ctx.metadata or {}),
            trace_ctx=base_ctx.trace_ctx,
            memory_context=base_ctx.memory_context,
            protected_intent=text,
            task_type=sq.get("domain", "general_qa"),
        )
        apply_lock = dict(lock)
        cap_hint = _pick_capability_for_sub(sq, force_mode, apply_lock)
        if force_mode:
            apply_lock["allowed_capabilities"] = [cap_hint]
        ctx.metadata = dict(ctx.metadata or {})
        ctx.metadata["intent_lock"] = apply_lock
        ctx.metadata["sub_question_id"] = sq_id
        sub_goal_id = str(sq.get("goal_id") or "")
        if sub_goal_id:
            ctx.metadata["sub_goal_id"] = sub_goal_id

        base_rt = (base_ctx.metadata or {}).get("runtime_task")
        if base_rt is not None:
            ctx.metadata["runtime_task"] = base_rt

        try:
            _cog, _plan, graph = await planner.plan_and_project(text, ctx, understanding=None)
        except Exception as exc:
            logger.warning("ExecutionPlanner failed for sub-question", sq_id=sq_id, error=str(exc))
            graph = _fallback_single_node(
                text, cap_hint, sq_id, ds_id, request, goal_id=sub_goal_id
            )
            _plan = None

        if not graph:
            graph = _fallback_single_node(
                text, cap_hint, sq_id, ds_id, request, goal_id=sub_goal_id
            )
            _plan = None

        try:
            from kernel.runtime.capability_governance import apply_governance_with_fallback

            graph = apply_governance_with_fallback(
                _plan,
                graph,
                ctx,
                text,
                node_id_prefix=f"{sq_id}:gov_fallback",
                sub_question_id=sq_id,
            )
            cg = (ctx.metadata or {}).get("capability_governance") or {}
            multi_gov_allowed.extend(cg.get("allowed", []))
            multi_gov_denied.extend(cg.get("denied", []))
            if not graph:
                graph = _fallback_single_node(
                    text, cap_hint, sq_id, ds_id, request, goal_id=sub_goal_id
                )
        except Exception as exc:
            logger.debug("Sub-question capability governance skipped", sq_id=sq_id, error=str(exc))

        for node in graph:
            nid = f"{sq_id}:{getattr(node, 'node_id', uuid.uuid4().hex[:8])}"
            node.node_id = nid
            node.query = text
            params = dict(getattr(node, "params", None) or {})
            params["sub_question_id"] = sq_id
            params["display_order"] = i + 1
            params["session_id"] = request.session_id
            params["user_id"] = request.user_id
            if sub_goal_id:
                params["goal_id"] = sub_goal_id
                node.goal_id = sub_goal_id
            else:
                gg = (base_ctx.metadata or {}).get("goal_graph") or {}
                root = str(gg.get("root_goal_id", "") or "")
                if root:
                    params.setdefault("goal_id", root)
                    node.goal_id = root
            if ds_id and "data" in (getattr(node, "capability_name", "") or ""):
                params.setdefault("data_source_id", ds_id)
            node.params = params
            if force_mode:
                want = _FORCE_MODE_CAPABILITY.get(force_mode, "")
                if want and getattr(node, "capability_name", "") != want:
                    node.capability_name = want
                    node.executor_type = "agent"
            merged_nodes.append(node)
            node_meta.append({"sub_question_id": sq_id, "node_id": nid})

    request.metadata = dict(request.metadata or {})
    request.metadata["multi_capability_governance"] = {
        "allowed": sorted(set(multi_gov_allowed)),
        "denied": sorted(set(multi_gov_denied)),
    }

    return merged_nodes, node_meta


def _fallback_single_node(
    text: str,
    capability: str,
    sq_id: str,
    data_source_id: str,
    request: Any,
    *,
    goal_id: str = "",
) -> list[Any]:
    from kernel.runtime.objects import ExecutionBudget, ExecutionNode

    params: dict[str, Any] = {
        "sub_question_id": sq_id,
        "session_id": request.session_id,
        "user_id": request.user_id,
    }
    if goal_id:
        params["goal_id"] = goal_id
    if data_source_id and "data" in capability:
        params["data_source_id"] = data_source_id
    if capability == "rag.retrieve":
        params.setdefault("top_k", 8)
        params.setdefault("sources", ["documents", "semantic_memory"])

    nid = f"{sq_id}:fallback"
    return [
        ExecutionNode(
            node_id=nid,
            capability_name=capability,
            executor_type="agent" if capability not in ("tool.datetime", "tool.weather") else "tool",
            query=text,
            params=params,
            depends_on=[],
            budget=ExecutionBudget(max_tokens=4096, max_latency_ms=30000),
            goal_id=goal_id,
        )
    ]