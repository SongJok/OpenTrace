"""P2 — self-optimizing runtime, semantic health signals, autonomous goals."""

from __future__ import annotations

import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_run_outcomes_records_executive_health():
    text = (ROOT / "kernel/cognitive_supervisor/run_outcomes.py").read_text(encoding="utf-8")
    assert "record_executive_turn_health" in text


def test_semantic_helpers_extracts_p0_p1_signals():
    from kernel.governance.semantic_helpers import extract_semantic_turn_signals

    req = type("R", (), {"metadata": {"cognitive_iteration": {"reflection_round": 2}}})()
    ctx = type(
        "C",
        (),
        {
            "metadata": {
                "web_coverage": {"coverage_score": 0.3},
                "goal_supervisor": {"split_from_root": True},
            }
        },
    )()
    sig = extract_semantic_turn_signals(req, ctx)
    assert sig["reflection_round"] == 2
    assert sig["coverage_score"] == 0.3
    assert sig["goal_supervisor_split"] is True


def test_self_optimizing_hints_on_high_drift():
    from kernel.runtime.self_optimizing_runtime import compute_optimization_hints

    report = compute_optimization_hints(
        health={"reasoning_drift": 0.8, "cognitive_saturation": 0.5},
        adaptive_risk_score=0.7,
        replanned=True,
        reflection_round=2,
    )
    assert len(report.hints) >= 1


def test_dispatch_autonomous_goal_proposals():
    text = (ROOT / "kernel/cognitive_supervisor/dispatch_enrichment.py").read_text(
        encoding="utf-8"
    )
    assert "autonomous_goal_discovery" in text


def test_semantic_metrics_extra_fields():
    from kernel.governance.semantic_metrics import compute_cognitive_health

    snap = compute_cognitive_health(
        evidence_count=2,
        fusion_confidence=0.8,
        hallucination_risk=0.1,
        critic_passed=True,
        reflection_round=1,
        claim_conflicts=2,
        coverage_score=0.4,
        goal_supervisor_split=True,
    )
    assert snap.extra.get("reflection_round") == 1
    assert snap.extra.get("claim_conflicts") == 2


def test_capability_evolution_module_exists():
    from kernel.capability_intelligence import evolution

    assert hasattr(evolution, "EvolutionEngine") or hasattr(evolution, "evolution_engine")


def test_finalize_turn_calls_semantic_evolution():
    text = (ROOT / "kernel/runtime/finalize_turn.py").read_text(encoding="utf-8")
    assert "finalize_semantic_and_evolution" in text


def test_evolution_hook_records_turn():
    from kernel.capability_intelligence.evolution_hook import record_capability_evolution_turn

    out = record_capability_evolution_turn(
        capability_types=["rag.query"],
        passed=True,
        latency_ms=50,
        evidence_quality=0.8,
        query_preview="test",
    )
    assert "recorded" in out or "skipped" in out


def test_autonomous_goal_mount_when_commit_enabled(monkeypatch):
    from infra.config import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "kernel_autonomous_goal_commit_enabled", True)
    from kernel.goal.autonomous_goal_discovery import (
        attach_proposals_to_metadata,
        maybe_mount_proposals_on_goal_graph,
        propose_goals_from_signals,
    )

    md = {
        "goal_graph": {
            "root_goal_id": "root1",
            "goals": [{"goal_id": "root1", "description": "q", "parent_id": None}],
        }
    }
    props = propose_goals_from_signals(query="风险分析", root_id="root1")
    attach_proposals_to_metadata(md, props)
    out = maybe_mount_proposals_on_goal_graph(md)
    assert out.get("mounted") or md.get("autonomous_goal_proposals")


def test_world_finalize_uses_fetch_merged():
    text = (ROOT / "kernel/world_turn_finalize.py").read_text(encoding="utf-8")
    assert "fetch_merged(" in text
    assert "fetch_merged_snapshot" not in text


def test_world_finalize_cross_process_wiring():
    text = (ROOT / "kernel/world_turn_finalize.py").read_text(encoding="utf-8")
    assert "kernel_world_model_cross_process_enabled" in text
    assert "CrossProcessWorldFacade" in text