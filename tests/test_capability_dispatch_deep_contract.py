"""Dispatch pipeline capability collection."""

from __future__ import annotations

from types import SimpleNamespace

from kernel.capability_runtime.dispatch_pipeline import collect_executed_capability_types


def test_collect_executed_capability_types():
    results = [
        SimpleNamespace(agent_type="rag", status="success"),
        SimpleNamespace(agent_type="web", status="success"),
    ]
    caps = collect_executed_capability_types(results)
    assert "document_retrieval" in caps or "rag" in caps