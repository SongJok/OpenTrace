"""Data Agent V2 — clarification, verification, error classifier, turn metadata."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_supervisor_wires_turn_metadata_module():
    sup = (ROOT / "agents" / "data_agent_v2" / "supervisor.py").read_text(encoding="utf-8")
    assert "turn_metadata" in sup
    assert "build_error_diagnosis_metadata" in sup
    assert "clarification_turn_metadata" in sup


def test_clarification_turn_metadata_shape():
    from agents.data_agent_v2.turn_metadata import clarification_turn_metadata

    md = clarification_turn_metadata(
        {"question_text": "哪张表？", "question_id": "q1", "suggested_options": ["orders"]}
    )
    assert md["turn_outcome"] == "clarification"
    assert md["needs_clarification"] is True
    assert md["pipeline_stage"] == "clarification_gate"


def test_verification_fail_turn_metadata():
    from agents.data_agent_v2.turn_metadata import verification_turn_metadata

    md = verification_turn_metadata({"status": "fail", "issues": [{"check": "metric"}]})
    assert md["verification_status"] == "fail"
    assert md["turn_outcome"] == "blocked"


def test_error_classifier_sql_connection_recovery():
    from agents.data_agent_v2.error_classifier import ErrorClassifier

    d = ErrorClassifier().classify_sql_error("connection refused to host")
    suggestions = ErrorClassifier().get_recovery_suggestions([d])
    assert d.category.value == "sql_connection"
    assert any(s.get("action") == "retry_later" for s in suggestions)


def test_build_error_diagnosis_metadata_empty_result():
    from agents.data_agent_v2.turn_metadata import build_error_diagnosis_metadata
    from agents.data_agent_v2.types import CognitiveContext

    ctx = CognitiveContext(query="count users", compiled_sql="SELECT 1", metrics=[])
    md = build_error_diagnosis_metadata(ctx, error="", rows=[])
    assert "error_diagnosis" in md
    assert "recovery_suggestions" in md
    cats = {x["category"] for x in md["error_diagnosis"]}
    assert "empty_result" in cats


def test_build_clarification_result_uses_turn_outcome():
    from agents.data_agent_v2.supervisor import DataAgentV2Supervisor
    from agents.base import TaskMessage
    from agents.data_agent_v2.types import CognitiveContext

    sup = DataAgentV2Supervisor()
    task = TaskMessage(task_id="t1", agent_type="data", query="查数据")
    ctx = CognitiveContext(
        query="查数据",
        clarification={
            "question_text": "请指定表",
            "suggested_options": ["orders"],
            "missing_entities": ["table"],
            "question_id": "q1",
        },
    )
    import time

    res = sup._build_clarification_result(task, ctx, time.monotonic())
    assert res.metadata.get("turn_outcome") == "clarification"
    assert res.metadata.get("needs_clarification") is True


def test_data_intelligence_runtime_merges_agent_metadata():
    from services.data_intelligence_runtime import attach_data_intelligence_to_metadata

    md = attach_data_intelligence_to_metadata(
        {
            "turn_outcome": "success",
            "verification_status": "pass",
            "sql": "SELECT 1",
            "row_count": 0,
        },
        query="KPI 同比",
        sql="SELECT 1",
        row_count=0,
    )
    assert md["turn_outcome"] == "success"
    assert md["verification_status"] == "pass"
    assert any(i.get("insight_type") == "kpi_reasoning" for i in md["data_intelligence"])