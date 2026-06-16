"""Runtime: ExecutionProjection merges enrichment params into DAG nodes."""

from __future__ import annotations

from kernel.runtime.cognitive.execution_projection import (
    ExecutionProjection,
    ProjectedCapability,
)


def test_to_execution_graph_injects_data_source_from_ctx():
    class _Ctx:
        session_id = "sess-1"
        user_id = "user-1"
        query = "GMV by region"
        metadata = {
            "data_source_context": {"data_source_id": "ds-99", "data_source_name": "sales"},
            "memory_injection_query": "expanded GMV",
            "conversation_summary": "User asked about sales last turn.",
        }

    proj = ExecutionProjection(
        rewritten_query="GMV",
        all_nodes=[
            ProjectedCapability(
                node_id="n1",
                capability_type="data.query",
                executor_type="agent",
                query="GMV by region",
                params={"dialect": "postgresql"},
            ),
        ],
    )
    nodes = proj.to_execution_graph(_Ctx())
    assert len(nodes) == 1
    p = nodes[0].params
    assert p["data_source_context"]["data_source_id"] == "ds-99"
    assert p["memory_injection_query"] == "expanded GMV"
    assert p["dialect"] == "postgresql"