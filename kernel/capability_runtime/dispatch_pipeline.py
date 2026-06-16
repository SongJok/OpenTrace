"""Pre/post capability dispatch: contract validation + intelligence feedback."""

from __future__ import annotations

import time
from typing import Any

from infra.observability.logger import get_logger
from kernel.protocol.runtime_contract import CapabilityRef

logger = get_logger(__name__)


def collect_planned_capability_types(
    plan: Any,
    execution_graph: list[Any] | None,
) -> list[str]:
    types: list[str] = []
    if execution_graph:
        for node in execution_graph:
            name = (
                getattr(node, "capability_name", "")
                or getattr(node, "capability_type", "")
                or ""
            )
            if name:
                try:
                    from kernel.runtime.capability import capability_registry

                    types.append(capability_registry.resolve_capability_type(str(name)))
                except Exception:
                    types.append(str(name))
        return list(dict.fromkeys(types))
    for t in getattr(plan, "subtasks", None) or []:
        ct = getattr(t, "capability_type", "") or ""
        if ct:
            types.append(ct)
    return list(dict.fromkeys(types))


def collect_executed_capability_types(agent_results: list[Any]) -> list[str]:
    """Distinct capability types from agent execution results."""
    types: list[str] = []
    try:
        from kernel.runtime.capability import capability_registry

        for r in agent_results or []:
            raw = (
                getattr(r, "capability_type", "")
                or getattr(r, "agent_type", "")
                or ""
            )
            if not raw:
                continue
            types.append(capability_registry.resolve_capability_type(str(raw)))
    except Exception:
        for r in agent_results or []:
            raw = getattr(r, "agent_type", "") or getattr(r, "capability_type", "")
            if raw:
                types.append(str(raw))
    return list(dict.fromkeys(types))


def validate_planned_capabilities(
    capability_types: list[str],
    *,
    environment: str = "default",
) -> dict[str, Any]:
    from kernel.capability_runtime.contract import validate_capability_execution

    violations: list[str] = []
    for ct in capability_types:
        ref = CapabilityRef(capability_type=ct)
        violations.extend(
            f"{ct}:{v}" for v in validate_capability_execution(ref, environment=environment)
        )
    try:
        from kernel.capability_runtime.topology import dependents_of

        for ct in capability_types:
            deps = dependents_of(ct)
            for dep in deps:
                if dep not in capability_types:
                    violations.append(f"{ct}:missing_dependency:{dep}")
    except Exception as exc:
        logger.warning("capability_topology_dependents_skipped", error=str(exc))
    return {"allowed": len(violations) == 0, "violations": violations}


def attach_goal_participation_metadata(
    agent_results: list[Any],
    *,
    root_goal_id: str,
    goal_description: str = "",
    trace_id: str = "",
    metadata_target: dict[str, Any] | None = None,
    ctx: Any | None = None,
    session_id: str = "",
) -> dict[str, Any]:
    """Build GoalParticipationGraph + RuntimeContribution turn bundle (Agent Runtime V3)."""
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_agent_runtime_v3_enabled", True)):
            return {}
        from kernel.agent_runtime.goal_participation import (
            contributions_from_agent_results as legacy_agent_contribs,
            merge_goal_contributions,
        )
        from kernel.runtime.evidence_runtime import (
            contributions_from_agent_results,
            enrich_evidence_with_graph,
            merge_turn_evidence,
        )

        sid = session_id or (
            str(getattr(ctx, "session_id", "") or "") if ctx is not None else ""
        )
        runtime_contribs = contributions_from_agent_results(
            agent_results,
            root_goal_id=root_goal_id,
            goal_description=goal_description,
            trace_id=trace_id,
            session_id=sid,
        )
        merged_turn, unified_evidence = merge_turn_evidence(
            agent_results,
            root_goal_id=root_goal_id,
            goal_description=goal_description,
            trace_id=trace_id,
            session_id=sid,
        )

        legacy_contribs = legacy_agent_contribs(
            agent_results,
            root_goal_id=root_goal_id,
            goal_description=goal_description,
            trace_id=trace_id,
        )
        graph = merge_goal_contributions(legacy_contribs, root_goal_id=root_goal_id)
        payload = graph.to_metadata()
        payload["runtime_contribution_turn"] = merged_turn.model_dump(mode="json")
        payload["runtime_contribution_count"] = len(runtime_contribs)

        if metadata_target is not None:
            metadata_target.update(payload)
            metadata_target["agent_runtime_v3"] = True
            metadata_target.update(merged_turn.to_metadata_dict())
            if ctx is not None:
                from kernel.runtime.cognitive_state.bus import apply_runtime_contribution_to_bus

                apply_runtime_contribution_to_bus(ctx, merged_turn)
            try:
                if bool(getattr(settings, "kernel_agent_runtime_p3_enabled", True)):
                    from kernel.agent_runtime.cognitive_runtimes import enrich_turn_cognitive_runtimes
                    from kernel.agent_runtime.unified_evidence import normalize_evidence_list

                    unified = list(unified_evidence)
                    if not unified:
                        unified = normalize_evidence_list(
                            agent_results,
                            goal_id=root_goal_id,
                            trace_id=trace_id,
                        )
                    p3 = enrich_turn_cognitive_runtimes(
                        unified_evidence=unified,
                        agent_results=agent_results,
                        goal_description=goal_description,
                        participation_metadata=payload,
                        turn_id=trace_id,
                    )
                    metadata_target.update(p3.to_metadata())
                    eg = enrich_evidence_with_graph(unified, query=goal_description)
                    metadata_target["evidence_runtime"] = eg
            except Exception as p3_exc:
                logger.debug("P3 cognitive runtime enrichment skipped", error=str(p3_exc))
            try:
                from kernel.agent_runtime.failure_from_contribution import (
                    record_turn_failure_signals,
                )

                fm = record_turn_failure_signals(
                    agent_results,
                    query_preview=goal_description[:80],
                    root_goal_id=root_goal_id,
                    goal_description=goal_description,
                    trace_id=trace_id,
                    session_id=sid,
                    merged=merged_turn,
                )
                metadata_target["failure_memory"] = fm
            except Exception as fm_exc:
                logger.debug("failure_memory_from_contribution_skipped", error=str(fm_exc))
            if ctx is not None:
                try:
                    from kernel.agent_runtime.world_decision_runtime import (
                        enrich_world_projection_for_turn,
                    )

                    wbundle = enrich_world_projection_for_turn(
                        ctx,
                        query=goal_description,
                        goal_description=goal_description,
                    )
                    metadata_target.update(wbundle.to_metadata_dict())
                except Exception as w_exc:
                    logger.debug("world_decision_runtime_skipped", error=str(w_exc))
        return payload
    except Exception as exc:
        logger.debug("Goal participation metadata skipped", error=str(exc))
        return {}


def resolve_root_goal_from_ctx(ctx: Any | None, request: Any | None = None) -> tuple[str, str]:
    """Extract root_goal_id and goal description from runtime context / request."""
    md: dict[str, Any] = {}
    if ctx is not None:
        md.update(dict(getattr(ctx, "metadata", None) or {}))
    if request is not None:
        req_md = getattr(request, "metadata", None) or {}
        gg = req_md.get("goal_graph") or {}
        if isinstance(gg, dict) and gg.get("root_goal_id"):
            md.setdefault("goal_graph", gg)
    gg = md.get("goal_graph") or {}
    root = ""
    if isinstance(gg, dict):
        root = str(gg.get("root_goal_id") or "")
    if not root:
        root = str(md.get("root_goal_id") or md.get("goal_id") or "")
    desc = str(
        md.get("protected_intent")
        or getattr(ctx, "query", "")
        or (getattr(request, "query", "") if request else "")
        or ""
    )
    return root, desc


def record_capability_outcomes(
    agent_results: list[Any],
    *,
    query_preview: str = "",
    default_evidence_quality: float = 0.5,
    root_goal_id: str = "",
    goal_description: str = "",
    metadata_target: dict[str, Any] | None = None,
    trace_id: str = "",
    ctx: Any | None = None,
) -> None:
    try:
        from infra.config.settings import settings

        if root_goal_id and bool(getattr(settings, "kernel_agent_runtime_v3_enabled", True)):
            attach_goal_participation_metadata(
                agent_results,
                root_goal_id=root_goal_id,
                goal_description=goal_description,
                trace_id=trace_id,
                metadata_target=metadata_target,
                ctx=ctx,
            )

        if not bool(getattr(settings, "kernel_capability_intelligence_enabled", True)):
            return
        from kernel.capability_intelligence.feedback import CapabilityFeedbackLoop
        from kernel.capability_intelligence.profile import ExecutionRecord
        from kernel.capability_intelligence.profiler import capability_profiler

        loop = CapabilityFeedbackLoop(capability_profiler)
        now = time.time()
        for r in agent_results:
            md = getattr(r, "metadata", None) or {}
            ctype = (
                getattr(r, "capability_type", "")
                or md.get("capability_type")
                or getattr(r, "agent_type", "")
                or "unknown"
            )
            try:
                from kernel.agent_runtime.manifest import get_manifest

                ent = get_manifest().get(str(getattr(r, "agent_type", "") or ""))
                if ent and ent.runtime == "tier2":
                    continue
            except Exception as exc:
                logger.debug("tier2_manifest_skip_failed", error=str(exc))
            success = str(getattr(r, "status", "")).lower() in ("ok", "success", "done")
            latency = int(getattr(r, "latency_ms", 0) or getattr(r, "duration_ms", 0) or 0)
            eq = default_evidence_quality
            evs = getattr(r, "evidence_objects", None) or []
            if evs:
                scores = [
                    float(getattr(e, "credibility_score", 0) or getattr(e, "score", 0) or 0)
                    for e in evs
                ]
                if scores:
                    eq = sum(scores) / len(scores)
            loop.record(
                ExecutionRecord(
                    capability_type=str(ctype),
                    query_preview=(query_preview or "")[:80],
                    success=success,
                    latency_ms=latency,
                    evidence_quality=eq,
                    timestamp=now,
                )
            )
            try:
                from kernel.capability_runtime.capability_os import get_capability_os
                from kernel.runtime.capability import capability_registry

                resolved = capability_registry.resolve_capability_type(str(ctype))
                cost = float(getattr(r, "acquisition_cost", 0) or getattr(r, "cost", 0) or 0.0)
                os = get_capability_os()
                os.record_invocation(
                    resolved,
                    success=success,
                    latency_ms=float(latency or 0),
                    cost=cost,
                )
                st = os.get_product_state(resolved)
                if st:
                    from observability.prometheus_export import record_capability_sla

                    record_capability_sla(resolved, st.sla.success_rate)
            except Exception as cap_os_exc:
                logger.debug("capability_os_prometheus_skipped", error=str(cap_os_exc))
    except Exception as exc:
        logger.debug("Capability outcome recording skipped", error=str(exc))