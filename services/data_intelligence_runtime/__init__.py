"""Data Intelligence Runtime — KPI reasoning, anomaly hints, root-cause scaffolding."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.base import AgentResult
from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DataIntelligenceInsight:
    insight_type: str
    summary: str
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "insight_type": self.insight_type,
            "summary": self.summary,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


def attach_data_intelligence_to_metadata(
    metadata: dict[str, Any],
    *,
    query: str,
    sql: str = "",
    row_count: int = 0,
    metric_names: list[str] | None = None,
) -> dict[str, Any]:
    """Merge data intelligence insights into agent metadata (sync)."""
    md = dict(metadata or {})
    intel = enrich_data_turn_outcomes(
        query=query,
        sql=sql,
        row_count=row_count,
        metric_names=metric_names,
    )
    md["data_intelligence"] = intel.get("data_intelligence", [])
    md["data_intelligence_runtime"] = intel.get("runtime", "data_intelligence_v1")
    return md


def enrich_data_turn_outcomes(
    *,
    query: str,
    sql: str = "",
    row_count: int = 0,
    metric_names: list[str] | None = None,
) -> dict[str, Any]:
    """Post-query intelligence layer (deterministic heuristics for enterprise contract)."""
    insights: list[dict[str, Any]] = []
    q = (query or "").lower()
    if row_count == 0 and sql:
        insights.append(
            DataIntelligenceInsight(
                insight_type="anomaly_empty_result",
                summary="Query returned no rows — verify filters and time range.",
                confidence=0.75,
            ).to_dict()
        )
    if any(k in q for k in ("kpi", "指标", "同比", "环比")):
        insights.append(
            DataIntelligenceInsight(
                insight_type="kpi_reasoning",
                summary="KPI-style question detected; prefer metric definitions and period comparison.",
                confidence=0.7,
                metadata={"metrics": list(metric_names or [])},
            ).to_dict()
        )
    if any(k in q for k in ("为什么", "原因", "root cause", "下降")):
        insights.append(
            DataIntelligenceInsight(
                insight_type="root_cause_hint",
                summary="Diagnostic intent — suggest drill-down dimensions and anomaly windows.",
                confidence=0.65,
            ).to_dict()
        )
    return {"data_intelligence": insights, "runtime": "data_intelligence_v1"}


async def run_data_intelligence_turn(
    request: Any,
    ctx: Any,
    *,
    event_cb: Any = None,
) -> Any:
    """Tier-1 data runtime: DataAgent + intelligence + Agent Runtime V3 goal participation."""
    from infra.config.settings import settings
    from kernel.capability_runtime.dispatch_pipeline import (
        record_capability_outcomes,
        resolve_root_goal_from_ctx,
    )
    from kernel.runtime.capability import capability_registry

    query = str(getattr(request, "query", "") or "")
    session_id = str(getattr(request, "session_id", "") or getattr(ctx, "session_id", "") or "")
    ctx.metadata = getattr(ctx, "metadata", None) or {}
    request.metadata = dict(getattr(request, "metadata", None) or {})

    root_goal, goal_desc = resolve_root_goal_from_ctx(ctx, request)
    trace_id = str(ctx.metadata.get("request_id") or request.metadata.get("request_id") or "")

    agent_results: list[AgentResult] = []
    executive_result: Any = None

    try:
        data_agent = capability_registry.get_agent("data")
    except KeyError:
        from kernel.cognitive_kernel import KernelResponse

        return KernelResponse(
            content="数据能力未注册，请检查 Agent Worker / bootstrap。",
            session_id=session_id,
            route="data_intelligence_error",
            validation_score=0.0,
            passed_validation=False,
            hallucination_risk=0.0,
            intent_category="data",
            intent_complexity="error",
            total_latency_ms=0,
            metadata={"error": "data_agent_not_registered"},
        )

    from agents.base import TaskMessage

    task_id = str(request.metadata.get("request_id") or session_id or "data-intel")
    task = TaskMessage(
        task_id=task_id,
        agent_type="data",
        query=query,
        params=dict(request.metadata.get("data_params") or {}),
        session_id=session_id or None,
        user_id=getattr(request, "user_id", None),
    )
    task.params.setdefault("goal_id", root_goal)
    task.params.setdefault("session_id", session_id)

    if bool(getattr(settings, "kernel_agent_runtime_v3_enabled", True)):
        from kernel.agent_runtime.executor import agent_runtime_executor

        contrib = await agent_runtime_executor.execute_task(
            data_agent,
            task,
            goal_id=root_goal,
            goal_description=goal_desc,
            capability_type="data_query",
            trace_id=trace_id,
        )
        agent_results.append(agent_runtime_executor.contribution_to_agent_result(contrib))
    else:
        agent_results.append(await data_agent.execute(task))

    primary = agent_results[0]
    sql = str((primary.metadata or {}).get("sql") or "")
    row_count = int((primary.metadata or {}).get("row_count") or 0)
    intel = enrich_data_turn_outcomes(query=query, sql=sql, row_count=row_count)
    primary.metadata = dict(primary.metadata or {})
    primary.metadata.update(attach_data_intelligence_to_metadata(primary.metadata, query=query, sql=sql, row_count=row_count))

    record_capability_outcomes(
        agent_results,
        query_preview=query[:80],
        root_goal_id=root_goal,
        goal_description=goal_desc,
        metadata_target=ctx.metadata,
        trace_id=trace_id,
        ctx=ctx,
    )

    try:
        from kernel.goal.goal_runtime_hooks import GoalRuntimeHooks

        hooks = GoalRuntimeHooks.from_context(ctx)
        if hooks is not None:
            hooks.on_phase("complete", note="data_intelligence_turn")
            if getattr(primary, "evidence_objects", None):
                hooks.record_evidence_ids(primary.evidence_objects)
    except Exception as exc:
        logger.warning("data_intelligence_goal_hooks_skipped", error=str(exc))

    try:
        import hashlib

        from world.world_slice_hooks import maybe_publish_execution_slice

        sql_hash = hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16] if sql else ""
        await maybe_publish_execution_slice(
            session_id=session_id,
            metadata={
                "phase": "data_verified" if primary.status == "success" else "data_error",
                "sql_hash": sql_hash,
                "row_count": row_count,
            },
        )
    except Exception as exc:
        logger.debug("data_intelligence_world_slice_skipped", error=str(exc))

    if getattr(settings, "kernel_data_intelligence_route_executive", False):
        from kernel.runtime.cognitive_executive import CognitiveExecutive

        executive_result = await CognitiveExecutive().execute(query, ctx, event_cb=event_cb)
        return executive_result

    content = primary.content or ""
    if intel.get("data_intelligence"):
        hints = "; ".join(i.get("summary", "") for i in intel["data_intelligence"][:2])
        if hints and hints not in content:
            content = f"{content}\n\n[Data Intelligence]\n{hints}".strip()

    from kernel.runtime.cognitive_executive import CognitiveExecutiveResult

    result = CognitiveExecutiveResult(
        answer=content,
        evidence_objects=list(getattr(primary, "evidence_objects", None) or []),
        risk_level="low",
        metadata={
            **primary.metadata,
            "data_intelligence_turn": True,
            "data_intelligence": intel.get("data_intelligence", []),
            "goal_participation": ctx.metadata.get("goal_participation"),
            "agent_runtime_v3": ctx.metadata.get("agent_runtime_v3"),
            "route": "data_intelligence",
            "confidence": float(primary.confidence or 0.5),
        },
    )
    return result