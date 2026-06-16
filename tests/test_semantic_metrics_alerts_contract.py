"""Semantic OS metrics + alerts contract (phase 5)."""

from __future__ import annotations

from governance.semantic_alerts import evaluate_health_alerts, export_turn_observability
from governance.semantic_metrics import compute_cognitive_health
from governance.semantic_metrics_pipeline import get_semantic_metrics_pipeline


class TestSemanticAlerts:
    def test_reasoning_drift_warn(self):
        alerts = evaluate_health_alerts(
            {"reasoning_drift": 0.6, "goal_stability": 1.0, "memory_pollution_risk": 0.1},
            {"avg_reasoning_drift": 0.5},
        )
        codes = [a["code"] for a in alerts]
        assert "reasoning_drift_warn" in codes or "reasoning_drift_critical" in codes

    def test_export_turn_observability(self):
        snap = compute_cognitive_health(
            evidence_count=2,
            fusion_confidence=0.8,
            hallucination_risk=0.7,
            critic_passed=False,
            replanned=True,
        ).to_dict()
        out = export_turn_observability(
            "s1",
            turn_snapshot=snap,
            session_trend={"turns": 3, "avg_reasoning_drift": 0.6, "avg_goal_stability": 0.9},
            route="cognitive_runtime_v2",
        )
        assert out["session_id"] == "s1"
        assert "alerts" in out
        assert out["alert_count"] >= 1

    def test_pipeline_session_trend(self):
        pipe = get_semantic_metrics_pipeline()
        pipe.record_turn(
            "s-alert",
            evidence_count=1,
            fusion_confidence=0.5,
            hallucination_risk=0.2,
            critic_passed=True,
            route="test",
        )
        trend = pipe.session_trend("s-alert")
        assert trend["turns"] == 1