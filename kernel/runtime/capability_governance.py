"""执行前能力治理 + 运行时元数据增强。"""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger
from kernel.capability_runtime.metadata import enrich_capability_ref
from kernel.governance.capability_governor import CapabilityGovernor
from kernel.protocol.runtime_contract import CapabilityRef, Constraints

logger = get_logger(__name__)

GOVERNANCE_FALLBACK_CAPABILITY = "model.answer"


def govern_capabilities_for_plan(
    plan: Any,
    execution_graph: list[Any] | None,
    ctx: Any,
) -> tuple[list[str], list[str]]:
    """
    按 RuntimeTask 约束校验计划中每个能力。
    返回 (允许的能力名列表, 拒绝的能力名列表)。
    """
    rt = (getattr(ctx, "metadata", None) or {}).get("runtime_task")
    if rt is not None:
        constraints = rt.constraints
    else:
        constraints = Constraints(
            allowed_capabilities=list(getattr(ctx, "allowed_capabilities", None) or []),
            disallowed_capabilities=list(getattr(ctx, "disallowed_capabilities", None) or []),
            max_parallel=int(
                (getattr(ctx, "cognitive_budget", None) or {}).get("max_capabilities", 5) or 5
            ),
            relevance_threshold=float(getattr(ctx, "relevance_threshold", 0.35) or 0.35),
        )

    gov = CapabilityGovernor()
    allowed: list[str] = []
    denied: list[str] = []

    names: list[str] = []
    if execution_graph:
        for n in execution_graph:
            cap = getattr(n, "capability_name", "") or getattr(n, "capability_type", "")
            if cap:
                names.append(cap)
    else:
        for st in getattr(plan, "subtasks", []) or []:
            cap = getattr(st, "capability_type", "") or getattr(st, "agent_type", "")
            if cap:
                names.append(cap)

    for cap_name in names:
        ref = enrich_capability_ref(
            CapabilityRef(capability_type=cap_name, capability_name=cap_name)
        )
        result = gov.check(ref, constraints)
        if result.allowed:
            allowed.append(cap_name)
        else:
            denied.extend(result.denied or [cap_name])

    ctx.metadata = ctx.metadata or {}
    ctx.metadata["capability_governance"] = {
        "allowed": allowed,
        "denied": denied,
    }
    return allowed, denied


def record_governance_denials(
    denied: list[str],
    query: str,
    *,
    resolution: str = GOVERNANCE_FALLBACK_CAPABILITY,
) -> None:
    """将治理拦截写入 FailureMemory（避免静默丢弃）。"""
    if not denied:
        return
    try:
        from kernel.capability_intelligence.failure_memory import failure_memory

        for cap in set(denied):
            failure_memory.record_from_result(
                capability_type=cap,
                query=query,
                success=False,
                error_msg=f"governance_denied: fallback={resolution}",
            )
    except Exception as exc:
        logger.debug("record_governance_denials skipped", error=str(exc))


def _fallback_allowed(ctx: Any) -> bool:
    rt = (getattr(ctx, "metadata", None) or {}).get("runtime_task")
    if rt is not None:
        constraints = rt.constraints
    else:
        constraints = Constraints(
            allowed_capabilities=list(getattr(ctx, "allowed_capabilities", None) or []),
            disallowed_capabilities=list(getattr(ctx, "disallowed_capabilities", None) or []),
        )
    ref = CapabilityRef(
        capability_type=GOVERNANCE_FALLBACK_CAPABILITY,
        capability_name=GOVERNANCE_FALLBACK_CAPABILITY,
    )
    return CapabilityGovernor().check(ref, constraints).allowed


def build_governance_fallback_node(
    query: str,
    ctx: Any,
    *,
    node_id: str = "gov_fallback",
    sub_question_id: str = "",
) -> Any:
    from kernel.runtime.objects import ExecutionBudget, ExecutionNode

    params: dict[str, Any] = {
        "session_id": getattr(ctx, "session_id", ""),
        "user_id": getattr(ctx, "user_id", ""),
        "governance_fallback": True,
        "original_denied": list(
            (ctx.metadata or {}).get("capability_governance", {}).get("denied", [])
        ),
    }
    if sub_question_id:
        params["sub_question_id"] = sub_question_id
    return ExecutionNode(
        node_id=node_id,
        capability_name=GOVERNANCE_FALLBACK_CAPABILITY,
        executor_type="agent",
        query=query,
        params=params,
        depends_on=[],
        budget=ExecutionBudget(max_tokens=4096, max_latency_ms=30000),
    )


def apply_governance_with_fallback(
    plan: Any,
    execution_graph: list[Any] | None,
    ctx: Any,
    query: str,
    *,
    node_id_prefix: str = "gov_fallback",
    sub_question_id: str = "",
) -> list[Any]:
    """
    治理 → 过滤 → 若图为空则记录失败并注入 model.answer 节点。
    当回退能力被允许时，尽量不返回空图。
    """
    graph = list(execution_graph or [])
    allowed, denied = govern_capabilities_for_plan(plan, graph, ctx)
    graph = filter_execution_graph_by_governance(graph, ctx)

    if denied:
        record_governance_denials(denied, query)

    if graph:
        return graph

    if denied and _fallback_allowed(ctx):
        nid = f"{node_id_prefix}:{sub_question_id or 'main'}"
        fb = build_governance_fallback_node(
            query, ctx, node_id=nid, sub_question_id=sub_question_id
        )
        ctx.metadata = ctx.metadata or {}
        ctx.metadata["capability_governance"]["fallback_applied"] = True
        ctx.metadata["capability_governance"]["fallback_capability"] = (
            GOVERNANCE_FALLBACK_CAPABILITY
        )
        logger.info(
            "Governance fallback to model.answer",
            denied=denied,
            sub_question_id=sub_question_id or None,
        )
        return [fb]

    return graph


def filter_execution_graph_by_governance(
    execution_graph: list[Any],
    ctx: Any,
) -> list[Any]:
    """移除被拒绝的能力对应节点。"""
    denied = set((ctx.metadata or {}).get("capability_governance", {}).get("denied", []))
    if not denied:
        return execution_graph
    out: list[Any] = []
    for node in execution_graph:
        cap = getattr(node, "capability_name", "") or ""
        if cap in denied:
            logger.info("Capability node removed by governance", capability=cap)
            continue
        out.append(node)
    return out