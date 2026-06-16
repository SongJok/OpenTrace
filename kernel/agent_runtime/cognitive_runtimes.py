"""P3 cognitive runtimes — hypothesis, contradiction, reflection, self-optimization hooks."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from kernel.agent_runtime.unified_evidence import UnifiedEvidence


class Hypothesis(BaseModel):
    hypothesis_id: str
    statement: str
    confidence: float = 0.5
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    falsifying_evidence_ids: list[str] = Field(default_factory=list)
    status: str = "open"  # open | supported | refuted | inconclusive


class ContradictionRecord(BaseModel):
    evidence_id_a: str
    evidence_id_b: str
    severity: float = 0.5
    resolution_hint: str = ""
    resolved: bool = False


class ReflectionNote(BaseModel):
    turn_id: str = ""
    summary: str = ""
    failures: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    confidence_delta: float = 0.0


class SelfOptimizationSignal(BaseModel):
    capability_type: str
    success_rate_hint: float = 0.5
    latency_p95_hint_ms: float = 0.0
    recommended_action: str = ""  # degrade | promote | noop


class CognitiveRuntimeBundle(BaseModel):
    """Aggregated P3 signals for turn metadata / governance."""

    hypotheses: list[Hypothesis] = Field(default_factory=list)
    contradictions: list[ContradictionRecord] = Field(default_factory=list)
    reflection: ReflectionNote | None = None
    optimization_signals: list[SelfOptimizationSignal] = Field(default_factory=list)
    version: str = "cognitive_runtime_p3_v1"

    def to_metadata(self) -> dict[str, Any]:
        return {"cognitive_runtime_p3": self.model_dump(mode="json")}


def build_hypotheses_from_evidence(
    unified: list[UnifiedEvidence],
    *,
    goal_description: str = "",
) -> list[Hypothesis]:
    out: list[Hypothesis] = []
    for i, u in enumerate(unified):
        claims = u.claims or ([u.content[:240]] if u.content else [])
        for j, claim in enumerate(claims):
            if not claim.strip():
                continue
            out.append(
                Hypothesis(
                    hypothesis_id=f"{u.evidence_id}:h{j}",
                    statement=claim.strip(),
                    confidence=u.confidence,
                    supporting_evidence_ids=[u.evidence_id],
                )
            )
    if goal_description and not out:
        out.append(
            Hypothesis(
                hypothesis_id="goal:primary",
                statement=goal_description[:500],
                confidence=0.4,
            )
        )
    return out


def detect_contradictions(unified: list[UnifiedEvidence]) -> list[ContradictionRecord]:
    records: list[ContradictionRecord] = []
    by_id = {u.evidence_id: u for u in unified}
    for u in unified:
        for link in u.contradiction_links:
            other = by_id.get(link)
            if other:
                records.append(
                    ContradictionRecord(
                        evidence_id_a=u.evidence_id,
                        evidence_id_b=other.evidence_id,
                        severity=min(1.0, abs(u.confidence - other.confidence) + 0.2),
                        resolution_hint="rank_and_supersede",
                    )
                )
    return records


def build_reflection_from_results(
    agent_results: list[Any],
    *,
    turn_id: str = "",
) -> ReflectionNote:
    failures = []
    for r in agent_results or []:
        st = str(getattr(r, "status", "")).lower()
        if st not in ("success", "ok", "done"):
            failures.append(f"{getattr(r, 'agent_type', '?')}: {getattr(r, 'error', st)}")
    improvements = []
    if failures:
        improvements.append("retry_with_substitute_capability")
        improvements.append("narrow_goal_scope")
    return ReflectionNote(
        turn_id=turn_id,
        summary=f"{len(agent_results or [])} agent results, {len(failures)} failures",
        failures=failures,
        improvements=improvements,
        confidence_delta=-0.1 * len(failures),
    )


def optimization_signals_from_participation(
    participation: dict[str, Any] | None,
) -> list[SelfOptimizationSignal]:
    if not participation:
        return []
    edges = participation.get("edges") or []
    signals: list[SelfOptimizationSignal] = []
    for e in edges:
        if not isinstance(e, dict):
            continue
        cap = str(e.get("capability_type") or "")
        if not cap:
            continue
        delta = float(e.get("goal_delta") or 0.0)
        action = "promote" if delta > 0.15 else "degrade" if delta < -0.1 else "noop"
        signals.append(
            SelfOptimizationSignal(
                capability_type=cap,
                success_rate_hint=0.5 + delta * 0.5,
                recommended_action=action,
            )
        )
    return signals


def enrich_turn_cognitive_runtimes(
    *,
    unified_evidence: list[UnifiedEvidence],
    agent_results: list[Any],
    goal_description: str = "",
    participation_metadata: dict[str, Any] | None = None,
    turn_id: str = "",
) -> CognitiveRuntimeBundle:
    participation = (participation_metadata or {}).get("goal_participation")
    return CognitiveRuntimeBundle(
        hypotheses=build_hypotheses_from_evidence(unified_evidence, goal_description=goal_description),
        contradictions=detect_contradictions(unified_evidence),
        reflection=build_reflection_from_results(agent_results, turn_id=turn_id),
        optimization_signals=optimization_signals_from_participation(participation),
    )