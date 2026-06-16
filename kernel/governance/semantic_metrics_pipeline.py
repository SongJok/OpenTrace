"""Cross-turn semantic OS metrics (cognitive health trends) — canonical."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict
from typing import Any

from kernel.governance.semantic_metrics import CognitiveHealthSnapshot, compute_cognitive_health

_MAX_SESSION_HISTORY = 32


class SemanticMetricsPipeline:
    def __init__(self) -> None:
        self._by_session: dict[str, deque[dict[str, Any]]] = {}

    def record_turn(
        self,
        session_id: str,
        *,
        evidence_count: int,
        fusion_confidence: float,
        hallucination_risk: float,
        critic_passed: bool | None,
        replanned: bool = False,
        refine_reexec: bool = False,
        goal_transition_rejected: bool = False,
        sub_goal_count: int = 0,
        route: str = "",
        reflection_round: int = 0,
        claim_conflicts: int = 0,
        coverage_score: float | None = None,
        goal_supervisor_split: bool = False,
    ) -> CognitiveHealthSnapshot:
        snap = compute_cognitive_health(
            evidence_count=evidence_count,
            fusion_confidence=fusion_confidence,
            hallucination_risk=hallucination_risk,
            critic_passed=critic_passed,
            replanned=replanned,
            refine_reexec=refine_reexec,
            goal_transition_rejected=goal_transition_rejected,
            sub_goal_count=sub_goal_count,
            reflection_round=reflection_round,
            claim_conflicts=claim_conflicts,
            coverage_score=coverage_score,
            goal_supervisor_split=goal_supervisor_split,
        )
        sid = session_id or "default"
        if sid not in self._by_session:
            self._by_session[sid] = deque(maxlen=_MAX_SESSION_HISTORY)
        self._by_session[sid].append({"route": route, "health": asdict(snap)})
        return snap

    def session_trend(self, session_id: str) -> dict[str, Any]:
        hist = list(self._by_session.get(session_id or "default", []))
        if not hist:
            return {"turns": 0, "avg_reasoning_drift": 0.0, "avg_goal_stability": 1.0}
        drifts = [h["health"].get("reasoning_drift", 0.0) for h in hist]
        stabs = [h["health"].get("goal_stability", 1.0) for h in hist]
        n = len(hist)
        return {
            "turns": n,
            "avg_reasoning_drift": round(sum(drifts) / n, 4),
            "avg_goal_stability": round(sum(stabs) / n, 4),
            "latest": hist[-1]["health"],
        }


_pipeline: SemanticMetricsPipeline | None = None


def get_semantic_metrics_pipeline() -> SemanticMetricsPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = SemanticMetricsPipeline()
    return _pipeline