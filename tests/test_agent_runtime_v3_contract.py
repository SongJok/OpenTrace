"""Agent Runtime V3 — manifest SSOT, bootstrap parity, tier-2, unified evidence, contributions."""

from __future__ import annotations

import pytest
import yaml

from agents.base import AgentResult
from agents.bootstrap import expected_builtin_agent_types, instantiate_builtin_agents
from kernel.agent_runtime.manifest import (
    get_manifest,
    reload_manifest,
    validate_manifest_integrity,
)
from kernel.agent_runtime.sync import sync_manifest_to_runtime, validate_bootstrap_parity
from kernel.agent_runtime.tier2_registry import list_tier2_agent_types, tier2_registry
from kernel.agent_runtime.unified_evidence import normalize_evidence
from kernel.runtime.objects import Evidence, Provenance


def test_manifest_version_and_tier_lists():
    reload_manifest()
    m = get_manifest()
    assert m.version.startswith("5.")
    assert set(m.bootstrap_agent_types) == {"production", "data", "config", "rag"}
    assert "web" not in m.bootstrap_agent_types
    assert m.get("web") is None
    tier2 = set(m.tier2_node_keys())
    assert "data_intent" in tier2
    assert "data_verification" in tier2
    assert "data" not in tier2


def test_bootstrap_manifest_parity():
    reload_manifest()
    violations = validate_bootstrap_parity()
    assert violations == [], violations


def test_manifest_integrity():
    reload_manifest()
    assert validate_manifest_integrity() == []


def test_removed_capabilities_are_not_in_worker_or_bus():
    reload_manifest()
    m = get_manifest()
    expected = {"production", "data", "config", "rag"}
    assert set(m.worker_agent_types) == expected
    assert set(m.bus_eligible_agent_types()) == expected


def test_instantiate_builtin_matches_manifest(monkeypatch):
    reload_manifest()
    from infra.config.settings import settings

    monkeypatch.setattr(settings, "capability_profile", "production_intelligence")
    agents = instantiate_builtin_agents()
    assert tuple(sorted(agents.keys())) == tuple(sorted(expected_builtin_agent_types()))


def test_sync_manifest_populates_capability_contracts():
    reload_manifest()
    summary = sync_manifest_to_runtime(force=True)
    assert summary["contracts_synced"] >= 2
    from kernel.capability_runtime.contract import get_capability_contract

    c = get_capability_contract("data_query")
    assert c.owner_runtime == "tier1_data"
    assert c.max_latency_ms >= 60_000


def test_tier2_registry_covers_manifest_nodes():
    reload_manifest()
    manifest_nodes = set(get_manifest().tier2_node_keys())
    registered = set(list_tier2_agent_types())
    assert manifest_nodes == registered


def test_tier2_get_agent_instantiates_fresh():
    agent_a = tier2_registry.get_agent("data_intent")
    agent_b = tier2_registry.get_agent("data_intent")
    assert agent_a is not agent_b


def test_normalize_runtime_evidence_to_unified():
    ev = Evidence(
        content="row count 42",
        provenance=Provenance(source="data", source_type="agent", confidence=0.9),
        credibility_score=0.9,
        metadata={"sql": "SELECT 1", "goal_id": "g1"},
    )
    u = normalize_evidence(ev, goal_id="g1", capability_type="data_query")
    assert u.source_type == "data"
    assert u.goal_id == "g1"
    assert u.confidence == 0.9
    roundtrip = u.to_runtime_evidence()
    assert roundtrip.metadata.get("unified") is True


def test_contribution_from_agent_result_goal_delta():
    from kernel.agent_runtime.contribution import contribution_from_agent_result

    result = AgentResult(
        task_id="t1",
        agent_type="rag",
        status="success",
        content="answer",
        confidence=0.8,
        evidence_objects=[
            Evidence(
                content="chunk",
                provenance=Provenance(source="rag", source_type="agent", confidence=0.8),
                credibility_score=0.8,
            )
        ],
    )
    contrib = contribution_from_agent_result(
        result, goal_id="goal-root", goal_description="find docs"
    )
    assert contrib.capability_type == "document_retrieval"
    assert contrib.goal is not None
    assert contrib.goal.supports_goal is True
    assert contrib.goal.goal_delta > 0
    assert len(contrib.unified_evidence) >= 1
    d = contrib.to_agent_result_dict()
    assert d["metadata"]["agent_runtime_v3"] is True


def test_world_projection_counterfactual_budget():
    from kernel.agent_runtime.world_projection import (
        apply_counterfactual_assumption,
        build_projection_bundle_from_context,
    )

    class _Ctx:
        session_id = "s1"
        metadata = {"world_state": {"budget": 100.0}}

    bundle = build_projection_bundle_from_context(_Ctx())
    assert bundle.current is not None
    assert bundle.current.variables.get("budget") == 100.0
    cf = apply_counterfactual_assumption(
        bundle,
        assumption="budget cut 20%",
        variable_deltas={"budget": {"op": "scale", "factor": 0.8}},
    )
    assert cf.counterfactual is not None
    assert cf.counterfactual.variables["budget"] == 80.0


def test_dag_invoke_resolve_tier2():
    from kernel.agent_runtime.dag_invoke import resolve_agent

    agent = resolve_agent("data_intent", capability_registry=None)
    assert agent is not None
    assert agent.agent_type == "data_intent"


def test_record_capability_outcomes_writes_participation():
    from kernel.capability_runtime.dispatch_pipeline import record_capability_outcomes

    result = AgentResult(
        task_id="t2",
        agent_type="rag",
        status="success",
        content="ok",
        confidence=0.7,
    )
    md: dict = {}
    record_capability_outcomes(
        [result],
        root_goal_id="g-root",
        goal_description="find answer",
        metadata_target=md,
        trace_id="req-1",
    )
    assert md.get("goal_participation")
    assert md.get("agent_runtime_v3") is True


def test_cognitive_p3_enrichment():
    from kernel.agent_runtime.cognitive_runtimes import enrich_turn_cognitive_runtimes
    from kernel.agent_runtime.unified_evidence import normalize_evidence

    u = normalize_evidence(
        AgentResult(
            task_id="t", agent_type="rag", status="success", content="claim x", confidence=0.8
        ),
        goal_id="g1",
    )
    bundle = enrich_turn_cognitive_runtimes(
        unified_evidence=[u],
        agent_results=[],
        goal_description="explain claim",
        turn_id="turn-1",
    )
    assert bundle.hypotheses
    assert bundle.version == "cognitive_runtime_p3_v1"


@pytest.mark.asyncio
async def test_evidence_bus_idempotent_publish():
    from kernel.runtime.evidence_bus import EvidenceBus
    from kernel.runtime.objects import Evidence, Provenance

    bus = EvidenceBus()
    ev = Evidence(
        evidence_id="fixed-id-001",
        content="once",
        provenance=Provenance(source="rag", confidence=0.5),
    )
    assert await bus.publish(ev) is True
    assert await bus.publish(ev) is False
    collected = await bus.collect()
    assert len(collected) == 1


def test_deprecated_agent_registry_resolves_tier2():
    from agents.registry import AgentRegistry

    reg = AgentRegistry()
    assert reg.has_agent("data_intent")
    agent = reg.get_agent("data_intent")
    assert agent.agent_type == "data_intent"


def test_stream_metadata_merge_from_ctx():
    from kernel.agent_runtime.stream_metadata import merge_agent_runtime_v3_into_metadata

    ctx = type(
        "C",
        (),
        {"metadata": {"goal_participation": {"root_goal_id": "g1"}, "agent_runtime_v3": True}},
    )()
    out: dict = {}
    merge_agent_runtime_v3_into_metadata(out, ctx=ctx)
    assert out["goal_participation"]["root_goal_id"] == "g1"


async def test_publish_results_skips_duplicate_unified_ids():
    from agents.base import AgentResult
    from kernel.runtime.evidence_bus import EvidenceBus
    from kernel.runtime.objects import Evidence, Provenance

    bus = EvidenceBus()
    ev = Evidence(
        evidence_id="dup-unified-1",
        content="x",
        provenance=Provenance(source="rag", confidence=0.8),
        credibility_score=0.8,
    )
    await bus.publish(ev)
    r = AgentResult(
        task_id="t",
        agent_type="rag",
        status="success",
        content="x",
        confidence=0.8,
        evidence_objects=[ev],
        metadata={"goal_id": "g1", "request_id": "r1"},
    )
    published = await bus.publish_results([r])
    assert len(await bus.collect()) == 1
    assert len(published) <= 1


def test_manifest_yaml_parseable():
    path = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "kernel/agent_runtime/agent_topology_manifest.yaml"
    )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "entries" in data
    assert len(data["entries"]) >= 13
