"""Data Intelligence Runtime scaffolding."""

from __future__ import annotations

from services.data_intelligence_runtime import enrich_data_turn_outcomes


def test_kpi_and_root_cause_hints():
    out = enrich_data_turn_outcomes(
        query="为什么 KPI 同比下降？",
        sql="SELECT 1",
        row_count=10,
    )
    types = {i["insight_type"] for i in out["data_intelligence"]}
    assert "kpi_reasoning" in types
    assert "root_cause_hint" in types