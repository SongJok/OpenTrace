"""Turn bootstrap SSOT — intent_lock + world for Gateway/Kernel."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_agent_loop_plans_a_structured_intent():
    text = (ROOT / "kernel/agent_loop/runner.py").read_text(encoding="utf-8")
    assert "IntentPlan" in text
    assert "_plan_intent" in text


def test_kernel_run_uses_bootstrap():
    text = (ROOT / "kernel/cognitive_kernel.py").read_text(encoding="utf-8")
    assert "bootstrap_turn_intent" in text
    assert text.count("bootstrap_turn_intent") >= 2


def test_resume_turn_bootstrap():
    text = (ROOT / "kernel/runtime/resume_turn.py").read_text(encoding="utf-8")
    assert "bootstrap_turn_intent" in text


@pytest.mark.asyncio
async def test_bootstrap_sets_intent_lock():
    from kernel.cognitive_kernel import KernelRequest
    from kernel.turn_bootstrap import bootstrap_turn_intent

    req = KernelRequest(
        query="/help",
        session_id="s-boot",
        user_id="u1",
        metadata={},
    )
    out = await bootstrap_turn_intent(req, apply_multi_turn=False, apply_world_hydrate=False)
    assert req.metadata.get("intent_lock")
    assert out.intent_lock.task_type
    assert out.effective_query


def test_learning_flag_in_registry():
    text = (ROOT / "infra/config/flag_registry.py").read_text(encoding="utf-8")
    assert "kernel_agent_learning_auto_apply" in text
    assert "kernel_capability_intelligence_enabled" in text
