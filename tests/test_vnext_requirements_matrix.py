"""Programmatic checklist against docs/ARCHITECTURE_REQUIREMENTS_MATRIX.md."""

from __future__ import annotations

from pathlib import Path


def test_matrix_doc_exists():
    p = Path(__file__).resolve().parents[1] / "docs" / "ARCHITECTURE_REQUIREMENTS_MATRIX.md"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "CognitiveSupervisor" in text
    assert "RuntimeGateway" in text


def test_kernel_entry_uses_runtime_gateway():
    src = (Path(__file__).resolve().parents[1] / "kernel" / "cognitive_kernel.py").read_text(
        encoding="utf-8"
    )
    assert "get_runtime_gateway" in src


def test_goal_package_exports_multi_goal():
    import kernel.goal as g

    assert hasattr(g, "build_sub_goal_bindings")
    assert hasattr(g, "evolve_sub_goals_after_multi_execution")


def test_governance_policy_engines_importable():
    from governance.cognitive_policy_engine import CognitivePolicyEngine

    assert CognitivePolicyEngine().evaluate_planning(
        intent_category="general", sub_goal_count=0, max_steps=3
    ).allowed


def test_goal_replay_snapshot_on_artifact():
    from kernel.cognitive_supervisor.run_outcomes import build_runtime_artifact

    ctx = type(
        "C",
        (),
        {"metadata": {"goal_graph": {"root_goal_id": "g"}, "goal_world_projection": {}}},
    )()
    req = type("R", (), {"session_id": "s", "metadata": {"request_id": "r", "goal_graph": {"root_goal_id": "g"}}})()
    result = type(
        "Res",
        (),
        {"answer": "x", "evidence_objects": [], "fusion_result": None, "critic_result": None, "rewrite_trace": ""},
    )()
    art = build_runtime_artifact(result, req, ctx=ctx)
    snap = art.execution_trace.metadata.get("goal_replay_snapshot") or {}
    assert snap.get("goal_graph") is not None


def test_replay_contract_on_artifact_trace():
    from kernel.cognitive_supervisor.run_outcomes import build_runtime_artifact

    req = type("R", (), {"session_id": "s", "metadata": {"request_id": "r", "goal_graph": {"root_goal_id": "g"}}})()
    result = type(
        "Res",
        (),
        {
            "answer": "ok",
            "evidence_objects": [],
            "fusion_result": None,
            "critic_result": None,
            "rewrite_trace": "",
        },
    )()
    art = build_runtime_artifact(result, req)
    rc = art.execution_trace.metadata.get("replay_contract") or {}
    assert rc.get("valid") is True
    assert rc.get("root_goal_id") == "g"


def test_goal_execution_outcomes():
    from kernel.goal.goal_execution_outcomes import record_goal_execution_outcomes

    ctx = type("C", (), {"metadata": {}})()
    node = type("N", (), {"node_id": "n1", "goal_id": "g1", "params": {}, "capability_name": "data.query"})()
    res = type("R", (), {"status": "ok", "error": ""})()
    out = record_goal_execution_outcomes(ctx, [node], [res])
    assert "g1" in out
    assert ctx.metadata["goal_execution_outcomes"]["g1"][0]["status"] == "ok"


def test_pytest_pythonpath_configured():
    toml = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert "pythonpath" in toml and "." in toml