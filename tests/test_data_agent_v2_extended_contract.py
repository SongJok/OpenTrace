"""Data Agent V2 + Data Intelligence — extended architecture contracts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


class TestDataAgentV2DagContracts:
    def test_build_cognitive_dag_includes_verification_when_verifier_on(self):
        from agents.data_agent_v2.dag_builder import build_cognitive_dag

        enabled = {
            "intent": True,
            "entity": True,
            "metric": True,
            "time": True,
            "join": False,
            "semantic": True,
            "planner": True,
            "compiler": True,
            "verifier": True,
        }
        spec = build_cognitive_dag("销售额同比", enabled, parallel=True)
        node_ids = [n.node_id for n in spec.nodes]
        assert "verification" in node_ids
        assert "compiler" in node_ids
        v = next(n for n in spec.nodes if n.node_id == "verification")
        assert v.depends_on == ["compiler"]

    def test_validate_dag_spec_catches_missing_dependency(self):
        from agents.data_agent_v2.dag_builder import DagNodeSpec, DagPlanSpec, validate_dag_spec

        spec = DagPlanSpec(
            nodes=[
                DagNodeSpec(
                    node_id="compiler",
                    agent_type="data_compiler",
                    query="q",
                    depends_on=["planner"],
                )
            ]
        )
        errs = validate_dag_spec(spec)
        assert any("missing planner" in e for e in errs)

    def test_supervisor_declares_clarification_and_verification_stages(self):
        sup = (ROOT / "agents" / "data_agent_v2" / "supervisor.py").read_text(encoding="utf-8")
        assert "verification" in sup.lower() or "Verification" in sup
        assert "DataAgentV2Supervisor" in sup
        ver = (ROOT / "agents" / "data_agent_v2" / "verification_agent.py").read_text(encoding="utf-8")
        assert "class" in ver and "Agent" in ver


class TestDataIntelligenceRuntimeExtended:
    def test_attach_data_intelligence_preserves_sql_metadata(self):
        from services.data_intelligence_runtime import attach_data_intelligence_to_metadata

        md = attach_data_intelligence_to_metadata(
            {"sql": "SELECT 1", "row_count": 0},
            query="KPI 为什么下降",
            sql="SELECT 1",
            row_count=0,
        )
        assert md.get("data_intelligence_runtime") == "data_intelligence_v1"
        assert isinstance(md.get("data_intelligence"), list)

    def test_empty_result_anomaly_insight(self):
        from services.data_intelligence_runtime import enrich_data_turn_outcomes

        out = enrich_data_turn_outcomes(query="count users", sql="SELECT 1", row_count=0)
        types = {i["insight_type"] for i in out["data_intelligence"]}
        assert "anomaly_empty_result" in types


@pytest.mark.asyncio
async def test_world_slice_hook_noop_when_disabled():
    from world.cross_process_world import get_cross_process_world
    from world.world_slice_hooks import maybe_publish_execution_slice

    await get_cross_process_world().reset_session("di-hook-off")
    await maybe_publish_execution_slice(
        session_id="di-hook-off",
        metadata={"phase": "data_verified"},
    )
    snap = await get_cross_process_world().fetch_merged("di-hook-off")
    assert "execution" not in snap.slices


@pytest.mark.asyncio
async def test_world_slice_hook_publishes_when_enabled(monkeypatch):
    from types import SimpleNamespace

    from world.cross_process_world import get_cross_process_world
    from world.world_slice_hooks import maybe_publish_execution_slice

    monkeypatch.setattr(
        "infra.config.settings.settings",
        SimpleNamespace(kernel_world_model_cross_process_enabled=True),
    )
    await get_cross_process_world().reset_session("di-hook")
    await maybe_publish_execution_slice(
        session_id="di-hook",
        metadata={"phase": "data_verified", "sql_hash": "abc"},
    )
    snap = await get_cross_process_world().fetch_merged("di-hook")
    assert snap.slices.get("execution", {}).get("phase") == "data_verified"