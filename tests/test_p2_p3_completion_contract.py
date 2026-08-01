"""P2/P3 completion — bootstrap, world finalize, document tenant scope."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_finalize_turn_calls_world_finalize():
    text = (ROOT / "kernel/runtime/finalize_turn.py").read_text(encoding="utf-8")
    assert "finalize_world_model_for_turn" in text


def test_document_retrieval_tenant_scope_helpers():
    text = (ROOT / "plugins/document_retrieval.py").read_text(encoding="utf-8")
    assert "accessible_document_predicate" in text
    assert "_apply_document_scope" in text


def test_runtime_params_include_tenant_workspace():
    text = (ROOT / "kernel/turn_enrichment.py").read_text(encoding="utf-8")
    assert '"tenant_id"' in text
    assert '"workspace_id"' in text


def test_cutover_runbook_documents_durable_worker_switch():
    text = (ROOT / "docs/runbooks/chatgpt_cutover.md").read_text(encoding="utf-8")
    assert "Worker" in text
    assert "Expand" in text and "Contract" in text
