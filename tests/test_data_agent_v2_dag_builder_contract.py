"""DataAgent V2 DAG builder — topology and dependency contract."""

from __future__ import annotations

from agents.data_agent_v2.dag_builder import build_cognitive_dag, validate_dag_spec


def _all_enabled() -> dict[str, bool]:
    return {
        "intent": True,
        "entity": True,
        "metric": True,
        "time": True,
        "join": True,
        "semantic": True,
        "planner": True,
        "compiler": True,
        "verifier": True,
    }


def test_metadata_fast_path_single_node():
    spec = build_cognitive_dag("表有哪些字段", _all_enabled(), is_metadata=True)
    assert len(spec.nodes) == 1
    assert spec.nodes[0].node_id == "intent"
    assert spec.metadata.get("fast_path") == "metadata"
    assert validate_dag_spec(spec) == []


def test_full_dag_dependency_closure():
    spec = build_cognitive_dag("统计销量", _all_enabled())
    assert validate_dag_spec(spec) == []
    ids = {n.node_id for n in spec.nodes}
    assert "semantic" in ids
    assert "planner" in ids
    assert "compiler" in ids
    assert "verification" in ids
    semantic = next(n for n in spec.nodes if n.node_id == "semantic")
    assert set(semantic.depends_on) <= {"intent", "entity"}
    compiler = next(n for n in spec.nodes if n.node_id == "compiler")
    assert compiler.depends_on == ["planner"]


def test_minimal_intent_only_when_others_disabled():
    enabled = {k: False for k in _all_enabled()}
    enabled["intent"] = True
    spec = build_cognitive_dag("q", enabled)
    assert [n.node_id for n in spec.nodes] == ["intent"]
    assert validate_dag_spec(spec) == []