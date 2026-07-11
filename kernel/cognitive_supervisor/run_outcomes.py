"""Supervisor-owned artifact, governance, and KernelResponse assembly."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any

from kernel.identity.system_identity import finalize_assistant_content
from kernel.protocol.runtime_contract import (
    ArtifactState,
    ExecutionTrace,
    Goal,
    GoalGraph,
    Provenance,
    RuntimeArtifact,
)


def governance_kwargs_from_ctx(ctx: Any, request: Any) -> dict[str, Any]:
    md = getattr(ctx, "metadata", None) or {}
    gg = (request.metadata or {}).get("goal_graph") or md.get("goal_graph") or {}
    goals = gg.get("goals") if isinstance(gg, dict) else []
    sub_count = max(0, len(goals) - 1) if isinstance(goals, list) else 0
    root_meta: dict[str, Any] = {}
    if isinstance(goals, list) and goals:
        root_id = gg.get("root_goal_id", "")
        for g in goals:
            if isinstance(g, dict) and g.get("goal_id") == root_id:
                root_meta = g.get("metadata") or {}
                break
    ar = md.get("adaptive_risk") or (request.metadata or {}).get("adaptive_risk") or {}
    return {
        "replanned": bool(md.get("refine_replan")),
        "refine_reexec": bool(md.get("refine_reexec")),
        "sub_goal_count": sub_count,
        "goal_transition_rejected": bool(root_meta.get("lifecycle_transition_rejected")),
        "adaptive_risk_level": str(ar.get("level", "")),
        "adaptive_risk_score": float(ar.get("score", 0.0) or 0.0),
    }


def _evidence_output_metadata(evidence: list[Any]) -> dict[str, Any]:
    """Promote Agent citations into the runtime's stable final envelope."""
    citations: list[dict[str, Any]] = []
    evidence_refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in evidence:
        item_citations = getattr(item, "citations", None) or []
        for citation in item_citations:
            if not isinstance(citation, dict):
                continue
            key = str(citation.get("source_version_id") or citation.get("chunk_id") or citation.get("id") or len(citations))
            if key not in seen:
                seen.add(key)
                citations.append(citation)
        metadata = getattr(item, "metadata", None) or {}
        provenance = metadata.get("provenance") if isinstance(metadata, dict) else {}
        evidence_refs.append({
            "evidence_id": getattr(item, "evidence_id", ""),
            "source_type": getattr(getattr(item, "provenance", None), "source", ""),
            "content": (getattr(item, "content", "") or "")[:240],
            "citations": item_citations[:3],
            "provenance": provenance or {},
            "state": getattr(item, "state", ""),
        })
    return {"citations": citations, "evidence_refs": evidence_refs}


def build_runtime_artifact(result: Any, request: Any, ctx: Any | None = None) -> RuntimeArtifact:
    artifact_meta_sink: dict[str, Any] = {}
    trace = ExecutionTrace(
        phases=[
            "rewrite",
            "understand",
            "plan",
            "execute",
            "evidence",
            "fusion",
            "critic",
        ],
        metadata={"rewrite_trace": getattr(result, "rewrite_trace", None) or ""},
    )
    conf = 0.0
    if getattr(result, "fusion_result", None):
        conf = float(getattr(result.fusion_result, "confidence", 0.0) or 0.0)
    critic = getattr(result, "critic_result", None)
    if critic:
        conf = max(conf, float(getattr(critic, "factuality", 0.0) or 0.0))

    evidence_list = list(getattr(result, "evidence_objects", None) or [])
    gg = (request.metadata or {}).get("goal_graph") or {}
    root_goal_id = str(gg.get("root_goal_id", "") or (request.metadata or {}).get("request_id", ""))
    req_id = str((request.metadata or {}).get("request_id", ""))
    try:
        from kernel.goal.goal_evidence_binding import (
            build_goal_evidence_binding,
            extract_evidence_ids,
            merge_binding_into_artifact_trace,
            stamp_evidence_goal_ids,
        )

        stamp_evidence_goal_ids(
            evidence_list, root_goal_id=root_goal_id, request_id=req_id
        )
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(
            artifact_meta_sink,
            subsystem="goal_evidence_binding",
            detail="stamp_evidence_goal_ids",
            exc=exc,
        )

    artifact_id = str(uuid.uuid4())
    artifact = RuntimeArtifact(
        artifact_id=artifact_id,
        evidence=evidence_list,
        execution_trace=trace,
        confidence=conf,
        provenance=Provenance(
            trace_id=str((request.metadata or {}).get("request_id", "")),
            planner_version="cognitive_planner_v2",
        ),
        state=ArtifactState.VALIDATED
        if getattr(critic, "passed", True)
        else ArtifactState.DRAFT,
        content=getattr(result, "answer", None) or "",
    )
    try:
        from kernel.goal.goal_evidence_binding import (
            build_goal_evidence_binding,
            extract_evidence_ids,
            merge_binding_into_artifact_trace,
        )

        binding = build_goal_evidence_binding(
            root_goal_id=root_goal_id,
            artifact_id=artifact_id,
            evidence_ids=extract_evidence_ids(evidence_list),
            session_id=getattr(request, "session_id", "") or "",
        )
        artifact.goal_evidence_binding = binding
        merge_binding_into_artifact_trace(artifact, binding)
        from kernel.protocol.behavior_contracts import ReplayContract, validate_replay_contract

        replay = ReplayContract(
            request_id=req_id,
            session_id=getattr(request, "session_id", "") or "",
            root_goal_id=root_goal_id,
            artifact_id=artifact_id,
            evidence_ids=list(binding.evidence_ids),
        )
        replay_violations = validate_replay_contract(replay)
        replay_policy: dict[str, Any] = {"allowed": True, "violations": []}
        try:
            from kernel.governance.governance_center import get_governance_center

            replay_policy = get_governance_center().evaluate_replay_mutation(
                {
                    "request_id": replay.request_id,
                    "session_id": replay.session_id,
                    "root_goal_id": replay.root_goal_id,
                    "artifact_id": replay.artifact_id,
                    "evidence_ids": list(replay.evidence_ids),
                }
            )
        except Exception as exc:
            from infra.observability.runtime_degraded import record_runtime_degradation

            record_runtime_degradation(
                artifact_meta_sink, subsystem="governance", detail="evaluate_replay_mutation", exc=exc
            )
        all_violations = list(replay_violations) + list(replay_policy.get("violations") or [])
        ws = (getattr(ctx, "metadata", None) or {}) if ctx else {}
        if ws.get("world_state_id"):
            trace.metadata["world_state"] = {
                "world_state_id": ws.get("world_state_id"),
                "parent_world_state_id": ws.get("parent_world_state_id"),
                "goal_world_version": ws.get("goal_world_version"),
            }
        trace.metadata["replay_contract"] = {
            "request_id": replay.request_id,
            "session_id": replay.session_id,
            "root_goal_id": replay.root_goal_id,
            "artifact_id": replay.artifact_id,
            "evidence_ids": replay.evidence_ids,
            "valid": len(all_violations) == 0 and replay_policy.get("allowed", True),
            "violations": all_violations,
            "policy": replay_policy,
        }
        if ctx and (getattr(ctx, "metadata", None) or {}).get("goal_execution_outcomes"):
            trace.metadata["goal_execution_outcomes"] = dict(
                (ctx.metadata or {})["goal_execution_outcomes"]
            )
        if ctx:
            try:
                from kernel.goal.goal_replay import snapshot_goal_for_replay

                trace.metadata["goal_replay_snapshot"] = snapshot_goal_for_replay(ctx)
            except Exception as exc:
                from infra.observability.runtime_degraded import record_runtime_degradation

                record_runtime_degradation(
                    artifact_meta_sink, subsystem="goal_replay", detail="snapshot_goal", exc=exc
                )
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(
            artifact_meta_sink, subsystem="goal_evidence_binding", detail="build_binding", exc=exc
        )
    deg = (artifact_meta_sink.get("semantic_observability") or {}).get("degradations")
    if deg and isinstance(trace.metadata, dict):
        trace.metadata.setdefault("runtime_degradations", deg)
    return artifact


def evaluate_executive_turn_governance(
    result: Any, request: Any, ctx: Any | None
) -> Any:
    from kernel.governance.governance_center import get_governance_center

    critic = getattr(result, "critic_result", None)
    hall_risk = float(getattr(critic, "hallucination_risk", 0.0) or 0.0) if critic else 0.0
    return get_governance_center().evaluate_turn(
        evidence_count=len(getattr(result, "evidence_objects", None) or []),
        fusion_confidence=float(
            getattr(result.fusion_result, "confidence", 0.0) or 0.0
        )
        if getattr(result, "fusion_result", None)
        else 0.0,
        hallucination_risk=hall_risk,
        critic_passed=getattr(critic, "passed", None) if critic else None,
        route="cognitive_runtime_v2",
        min_evidence=1
        if getattr(result, "plan", None) and getattr(result.plan, "subtasks", None)
        else 0,
        **governance_kwargs_from_ctx(ctx, request),
    )


def executive_result_to_kernel_response(
    result: Any, request: Any, total_ms: int, ctx: Any | None = None
) -> Any:
    from kernel.cognitive_kernel import KernelResponse

    if getattr(result, "policy_denied", False):
        return KernelResponse(
            content=finalize_assistant_content(
                result.answer or "", getattr(request, "query", "") or ""
            ),
            session_id=request.session_id,
            route="cognitive_runtime_v2_denied",
            validation_score=1.0,
            passed_validation=True,
            hallucination_risk=0.0,
            intent_category="blocked",
            intent_complexity=result.risk_level,
            total_latency_ms=total_ms,
            metadata={"policy_denied": True, "runtime": "v2"},
        )

    if ctx is not None:
        try:
            from kernel.goal.goal_progress import sync_goal_lifecycle_from_metadata

            sync_goal_lifecycle_from_metadata(ctx)
        except Exception as exc:
            from infra.observability.runtime_degraded import record_runtime_degradation

            record_runtime_degradation(
                getattr(ctx, "metadata", None) or {},
                subsystem="goal_progress",
                detail="sync_lifecycle_response",
                exc=exc,
            )

    critic = getattr(result, "critic_result", None)
    understanding = getattr(result, "understanding", None)
    artifact = build_runtime_artifact(result, request, ctx=ctx)
    hall_risk = getattr(critic, "hallucination_risk", 0.0) if critic else 0.0
    gov_bundle = evaluate_executive_turn_governance(result, request, ctx)
    try:
        from kernel.governance.semantic_metrics_pipeline import get_semantic_metrics_pipeline

        gkw = governance_kwargs_from_ctx(ctx, request)
        trend_snap = get_semantic_metrics_pipeline().record_turn(
            request.session_id,
            evidence_count=len(getattr(result, "evidence_objects", None) or []),
            fusion_confidence=float(
                getattr(result.fusion_result, "confidence", 0.0) or 0.0
            )
            if getattr(result, "fusion_result", None)
            else 0.0,
            hallucination_risk=float(hall_risk or 0.0),
            critic_passed=getattr(critic, "passed", None) if critic else None,
            route="cognitive_runtime_v2",
            replanned=gkw.get("replanned", False),
            refine_reexec=gkw.get("refine_reexec", False),
            goal_transition_rejected=gkw.get("goal_transition_rejected", False),
            sub_goal_count=gkw.get("sub_goal_count", 0),
        )
        gov_bundle.semantic_observability.setdefault(
            "cognitive_health_trend",
            get_semantic_metrics_pipeline().session_trend(request.session_id),
        )
        gov_bundle.semantic_observability.setdefault(
            "cognitive_health_turn", trend_snap.to_dict()
        )
        try:
            from kernel.governance.semantic_alerts import export_turn_observability

            trend = get_semantic_metrics_pipeline().session_trend(request.session_id)
            obs = export_turn_observability(
                request.session_id,
                turn_snapshot=trend_snap.to_dict(),
                session_trend=trend,
                route="cognitive_runtime_v2",
            )
            gov_bundle.semantic_observability["cognitive_health_export"] = obs
            gov_bundle.semantic_observability["semantic_alerts"] = obs.get("alerts", [])
        except Exception as exc:
            from infra.observability.runtime_degraded import record_runtime_degradation

            record_runtime_degradation(
                gov_bundle.semantic_observability,
                subsystem="semantic_alerts",
                detail="export_turn_observability",
                exc=exc,
            )
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(
            gov_bundle.semantic_observability,
            subsystem="semantic_metrics",
            detail="cognitive_health_turn",
            exc=exc,
        )

    meta_out: dict[str, Any] = {
        "cognitive_runtime_v2": True,
        "artifact": asdict(artifact) if hasattr(artifact, "__dataclass_fields__") else {},
        "evidence_count": len(getattr(result, "evidence_objects", None) or []),
        "semantic_observability": gov_bundle.semantic_observability,
        "goal_graph": (request.metadata or {}).get("goal_graph"),
        "governance": {
            "evidence": gov_bundle.evidence,
            "risk": gov_bundle.risk,
        },
        **_evidence_output_metadata(list(getattr(result, "evidence_objects", None) or [])),
        "trace_id": str((request.metadata or {}).get("request_id", "")),
    }
    exec_gov = (request.metadata or {}).get("governance")
    if exec_gov:
        meta_out["governance"]["executive"] = exec_gov
    if request.metadata.get("force_mode"):
        meta_out["force_mode"] = request.metadata.get("force_mode")
    if ctx and (getattr(ctx, "metadata", None) or {}).get("goal_execution_outcomes"):
        meta_out["goal_execution_outcomes"] = dict(
            (ctx.metadata or {})["goal_execution_outcomes"]
        )
    if ctx:
        ctx_md = getattr(ctx, "metadata", None) or {}
        if ctx_md.get("goal_participation"):
            meta_out["goal_participation"] = ctx_md["goal_participation"]
        if ctx_md.get("goal_participation_version"):
            meta_out["goal_participation_version"] = ctx_md["goal_participation_version"]
        if ctx_md.get("agent_runtime_v3"):
            meta_out["agent_runtime_v3"] = ctx_md["agent_runtime_v3"]
        if ctx_md.get("cognitive_runtime_p3"):
            meta_out["cognitive_runtime_p3"] = ctx_md["cognitive_runtime_p3"]
        if ctx_md.get("capability_evolution"):
            meta_out["capability_evolution"] = ctx_md["capability_evolution"]
        if ctx_md.get("goal_progress"):
            meta_out["goal_progress"] = dict(ctx_md["goal_progress"])
        if ctx_md.get("runtime_contribution_turn"):
            meta_out["runtime_contribution_turn"] = ctx_md["runtime_contribution_turn"]
        if ctx_md.get("cognitive_state_graph"):
            meta_out["cognitive_state_graph"] = ctx_md["cognitive_state_graph"]
        if ctx_md.get("failure_memory"):
            meta_out["failure_memory"] = ctx_md["failure_memory"]
        if ctx_md.get("evidence_runtime"):
            meta_out["evidence_runtime"] = ctx_md["evidence_runtime"]
        if ctx_md.get("world_projection"):
            meta_out["world_projection"] = ctx_md["world_projection"]
        if ctx_md.get("world_projection_version"):
            meta_out["world_projection_version"] = ctx_md["world_projection_version"]
        gg_out = ctx_md.get("goal_graph")
        if gg_out:
            meta_out["goal_graph"] = gg_out
    rc = (artifact.execution_trace.metadata or {}).get("replay_contract")
    if rc:
        meta_out["replay_contract"] = rc

    try:
        from kernel.goal.turn_outcomes import apply_turn_goal_and_memory_outcomes

        meta_out.update(
            apply_turn_goal_and_memory_outcomes(
                request=request,
                ctx=ctx,
                answer=result.answer or "",
                route="cognitive_runtime_v2",
                critic_passed=getattr(critic, "passed", None) if critic else None,
                artifact_id=artifact.artifact_id,
                evidence_ids=list(
                    (artifact.execution_trace.metadata or {}).get("replay_contract", {}).get(
                        "evidence_ids", []
                    )
                    or []
                ),
            )
        )
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(meta_out, subsystem="turn_outcomes", detail="goal_memory", exc=exc)

    try:
        from kernel.cognitive_supervisor.enterprise_outcomes import enrich_turn_enterprise_metadata

        enrich_turn_enterprise_metadata(
            request=request,
            ctx=ctx,
            result=result,
            critic_passed=getattr(critic, "passed", None) if critic else None,
            meta_out=meta_out,
        )
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(meta_out, subsystem="enterprise_outcomes", detail="enrich_turn", exc=exc)

    try:
        from kernel.governance.semantic_helpers import record_executive_turn_health

        health_bundle = record_executive_turn_health(
            session_id=str(getattr(request, "session_id", "") or ""),
            result=result,
            request=request,
            ctx=ctx,
        )
        obs = meta_out.setdefault("semantic_observability", {})
        if isinstance(obs, dict):
            obs["cognitive_health"] = health_bundle.get("cognitive_health")
            obs["session_trend"] = health_bundle.get("session_trend")
            if health_bundle.get("self_optimizing_runtime"):
                obs["self_optimizing_runtime"] = health_bundle["self_optimizing_runtime"]
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(meta_out, subsystem="semantic_health", detail="record_executive", exc=exc)
    try:
        from kernel.agent_runtime.stream_metadata import merge_agent_runtime_v3_into_metadata

        merge_agent_runtime_v3_into_metadata(
            meta_out,
            ctx=ctx,
            result_metadata=dict(getattr(result, "metadata", None) or {}),
        )
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(meta_out, subsystem="agent_runtime_v3", detail="merge_metadata", exc=exc)

    deg_trace = (artifact.execution_trace.metadata or {}).get("runtime_degradations")
    if deg_trace:
        obs = meta_out.setdefault("semantic_observability", {})
        if isinstance(obs, dict):
            obs.setdefault("degradations", [])
            if isinstance(obs["degradations"], list):
                obs["degradations"] = (obs["degradations"] + list(deg_trace))[-32:]

    return KernelResponse(
        content=finalize_assistant_content(
            result.answer or "", getattr(request, "query", "") or ""
        ),
        session_id=request.session_id,
        route=str(meta_out.get("route") or "cognitive_runtime_v2"),
        validation_score=getattr(critic, "factuality", 0.9) if critic else 0.9,
        passed_validation=getattr(critic, "passed", True) if critic else True,
        hallucination_risk=hall_risk,
        intent_category=getattr(understanding, "domain", "general")
        if understanding
        else "general",
        intent_complexity=result.risk_level,
        total_latency_ms=total_ms,
        metadata=meta_out,
    )


def build_stream_final_metadata(
    result: Any, request: Any, ctx: Any | None, artifact: RuntimeArtifact
) -> dict[str, Any]:
    gov_bundle = evaluate_executive_turn_governance(result, request, ctx)
    critic = getattr(result, "critic_result", None)
    stream_meta: dict[str, Any] = {
        "cognitive_runtime_v2": True,
        "artifact_id": artifact.artifact_id,
        "risk_level": getattr(result, "risk_level", "low"),
        "validation_score": getattr(critic, "factuality", 0.9) if critic else 0.9,
        "passed_validation": getattr(critic, "passed", True) if critic else True,
        "goal_graph": (request.metadata or {}).get("goal_graph")
        or ((getattr(ctx, "metadata", None) or {}).get("goal_graph")),
        "semantic_observability": gov_bundle.semantic_observability,
        "governance": {
            "evidence": gov_bundle.evidence,
            "risk": gov_bundle.risk,
        },
        **_evidence_output_metadata(list(getattr(result, "evidence_objects", None) or [])),
        "trace_id": str((request.metadata or {}).get("request_id", "")),
    }
    exec_gov = (request.metadata or {}).get("governance")
    if exec_gov:
        stream_meta["governance"]["executive"] = exec_gov
    if request.metadata.get("force_mode"):
        stream_meta["force_mode"] = request.metadata.get("force_mode")
    try:
        from kernel.goal.turn_outcomes import apply_turn_goal_and_memory_outcomes

        stream_meta.update(
            apply_turn_goal_and_memory_outcomes(
                request=request,
                ctx=ctx,
                answer=getattr(result, "answer", "") or "",
                route="cognitive_runtime_v2_stream",
                critic_passed=getattr(critic, "passed", None) if critic else None,
                artifact_id=artifact.artifact_id,
                evidence_ids=list(
                    (artifact.execution_trace.metadata or {}).get("replay_contract", {}).get(
                        "evidence_ids", []
                    )
                    or []
                ),
            )
        )
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(stream_meta, subsystem="turn_outcomes", detail="goal_memory_stream", exc=exc)
    try:
        from kernel.cognitive_supervisor.enterprise_outcomes import enrich_turn_enterprise_metadata

        enrich_turn_enterprise_metadata(
            request=request,
            ctx=ctx,
            result=result,
            critic_passed=getattr(critic, "passed", None) if critic else None,
            meta_out=stream_meta,
        )
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(stream_meta, subsystem="enterprise_outcomes", detail="enrich_stream", exc=exc)
    try:
        from kernel.agent_runtime.stream_metadata import merge_agent_runtime_v3_into_metadata

        merge_agent_runtime_v3_into_metadata(
            stream_meta,
            ctx=ctx,
            result_metadata=dict(getattr(result, "metadata", None) or {}),
        )
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(stream_meta, subsystem="agent_runtime_v3", detail="merge_stream", exc=exc)
    return stream_meta


def multi_question_to_kernel_response(mq: Any, request: Any, total_ms: int) -> Any:
    from kernel.cognitive_kernel import KernelResponse

    meta = dict(getattr(mq, "metadata", None) or {})
    if request.metadata.get("force_mode"):
        meta["force_mode"] = request.metadata.get("force_mode")
    meta["cognitive_supervisor"] = True
    for key in (
        "replay_contract",
        "goal_execution_outcomes",
        "sub_goal_bindings",
        "goal_evolution",
        "goal_graph",
    ):
        if key not in meta and (request.metadata or {}).get(key):
            meta[key] = request.metadata[key]
    try:
        from kernel.cognitive_supervisor.enterprise_outcomes import enrich_turn_enterprise_metadata

        enrich_turn_enterprise_metadata(
            request=request,
            ctx=None,
            result=mq,
            critic_passed=mq.passed_validation,
            meta_out=meta,
        )
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(
            meta, subsystem="enterprise_outcomes", detail="enrich_turn_metadata", exc=exc
        )
    return KernelResponse(
        content=finalize_assistant_content(
            mq.content or "", getattr(request, "query", "") or ""
        ),
        session_id=request.session_id,
        route=mq.route,
        validation_score=mq.validation_score,
        passed_validation=mq.passed_validation,
        hallucination_risk=mq.hallucination_risk,
        intent_category=mq.intent_category,
        intent_complexity="complex",
        total_latency_ms=total_ms,
        metadata=meta,
        state_patch=getattr(mq, "state_patch", None),
        result_refs=getattr(mq, "result_refs", None),
    )
