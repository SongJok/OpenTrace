"""Data agent attaches data intelligence metadata."""

from __future__ import annotations

from services.data_intelligence_runtime import attach_data_intelligence_to_metadata


def test_attach_data_intelligence_to_metadata():
    md = attach_data_intelligence_to_metadata(
        {"sql": "SELECT 1", "row_count": 0},
        query="KPI 同比",
        sql="SELECT 1",
        row_count=0,
    )
    assert "data_intelligence" in md
    assert isinstance(md["data_intelligence"], list)