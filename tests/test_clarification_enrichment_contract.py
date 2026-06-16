"""Clarification + turn enrichment wiring."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_clarification_enrichment_module():
    text = (ROOT / "kernel/clarification_enrichment.py").read_text(encoding="utf-8")
    assert "enrichment_blocks_from_params" in text
    assert "assembled_context" in text


def test_data_supervisor_sets_clarification_block():
    text = (ROOT / "agents/data_agent_v2/supervisor.py").read_text(encoding="utf-8")
    assert "clarification_enrichment_block" in text
    assert "enrichment_blocks_from_params" in text


def test_data_clarification_gate_appends_enrichment():
    text = (ROOT / "kernel/clarification_gate.py").read_text(encoding="utf-8")
    assert "clarification_enrichment_block" in text


def test_learning_auto_apply_in_flag_registry():
    text = (ROOT / "infra/config/flag_registry.py").read_text(encoding="utf-8")
    assert "kernel_agent_learning_auto_apply" in text
    assert "kernel_capability_intelligence_enabled" in text


def test_enrichment_blocks_from_params_multi_turn():
    from kernel.clarification_enrichment import enrichment_blocks_from_params

    block = enrichment_blocks_from_params(
        {
            "multi_turn_resolution": {
                "applied": True,
                "original_query": "那呢",
                "resolved_query": "华东 GMV 环比",
            },
            "assembled_context": {"state_block": "active_domain=data"},
        }
    )
    assert "华东" in block
    assert "会话状态" in block or "state" in block.lower() or "会话" in block