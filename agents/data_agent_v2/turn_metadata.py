"""Stable metadata shapes for Data Agent V2 turn outcomes (clarification, verification, errors)."""

from __future__ import annotations

from typing import Any

from agents.data_agent_v2.error_classifier import ErrorDiagnosis


def diagnosis_to_dict(d: ErrorDiagnosis) -> dict[str, Any]:
    return {
        "category": d.category.value,
        "severity": d.severity,
        "description": d.description,
        "repair_strategy": d.repair_strategy,
        "repairable": d.repairable,
    }


def build_error_diagnosis_metadata(
    ctx: Any,
    *,
    error: str = "",
    rows: list[dict] | None = None,
) -> dict[str, Any]:
    """Run ErrorClassifier and return turn-outcome fields for AgentResult.metadata."""
    from agents.data_agent_v2.error_classifier import ErrorClassifier

    classifier = ErrorClassifier()
    diagnoses = classifier.classify_runtime_issue(
        rows=rows or [],
        error=error or str(getattr(ctx, "execution_error", "") or ""),
        verification_report=getattr(ctx, "verification_report", None),
        ctx=ctx,
    )
    return {
        "error_diagnosis": [diagnosis_to_dict(d) for d in diagnoses[:8]],
        "recovery_suggestions": classifier.get_recovery_suggestions(diagnoses)[:5],
        "repair_prompt_preview": (classifier.get_repair_prompt(diagnoses) or "")[:500],
    }


def clarification_turn_metadata(clarification: dict[str, Any]) -> dict[str, Any]:
    """Canonical clarification block for frontend + turn_outcomes."""
    return {
        "needs_clarification": True,
        "clarification": dict(clarification),
        "turn_outcome": "clarification",
        "pipeline_stage": "clarification_gate",
    }


def verification_turn_metadata(report: dict[str, Any] | None) -> dict[str, Any]:
    rep = dict(report or {})
    status = str(rep.get("status") or "unknown")
    return {
        "verification_report": rep,
        "verification_status": status,
        "turn_outcome": "blocked" if status == "fail" else "verified",
        "pipeline_stage": "sql_verification",
    }


def build_data_success_evidence_objects(
    *,
    task_id: str,
    sql: str,
    rows: list[dict],
    confidence: float,
    elapsed_ms: int,
    verification_report: dict[str, Any] | None,
    evidence_dicts: list[dict[str, Any]],
) -> list[Any]:
    """Runtime Evidence list for Agent Runtime V3 strict (unified evidence normalization)."""
    from kernel.runtime.objects import Evidence, Provenance

    primary = Evidence(
        content=f"SQL query returned {len(rows)} rows",
        content_type="data",
        provenance=Provenance(
            source="data_agent_v2",
            source_type="sql",
            confidence=confidence,
        ),
        credibility_score=min(0.99, max(0.5, confidence)),
        relevance_score=1.0,
        acquisition_cost=elapsed_ms / 1000.0,
        metadata={
            "task_id": task_id,
            "sql": sql,
            "row_count": len(rows),
            "verification": verification_report,
            "agent_type": "data",
            "capability_type": "data_query",
        },
    )
    objects: list[Any] = [primary]
    for ev in evidence_dicts[1:6]:
        payload = ev.get("payload") or {}
        objects.append(
            Evidence(
                content=str(ev.get("source") or "analysis"),
                content_type=str(ev.get("source_type") or "analysis"),
                provenance=Provenance(
                    source=str(ev.get("source") or "data_agent_v2"),
                    source_type=str(ev.get("source_type") or "analysis"),
                    confidence=float(ev.get("credibility_score") or 0.75),
                ),
                credibility_score=float(ev.get("credibility_score") or 0.75),
                relevance_score=float(ev.get("relevance_score") or 0.8),
                metadata={"payload": payload, "task_id": task_id},
            )
        )
    return objects