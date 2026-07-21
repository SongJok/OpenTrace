"""Resume turn — RuntimeGateway path (no legacy CognitiveOrchestrator)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_resume_turn_via_gateway_calls_runtime_gateway(monkeypatch):
    from kernel.cognitive_kernel import KernelResponse
    from kernel.runtime import resume_turn as rt

    async def _fake_load(db, *, session_id, step_index):
        return "继续上次分析", {"route": "kernel"}

    gw = AsyncMock()
    gw.run = AsyncMock(
        return_value=KernelResponse(
            content="ok",
            session_id="sess-1",
            route="cognitive_executive",
            validation_score=0.9,
            passed_validation=True,
            intent_category="qa",
            metadata={"resume": True},
        )
    )

    monkeypatch.setattr(rt, "load_resume_context_from_trace", _fake_load)
    monkeypatch.setattr(
        "kernel.runtime_gateway.get_runtime_gateway",
        lambda: gw,
    )

    out = await rt.resume_turn_via_gateway(
        MagicMock(),
        session_id="sess-1",
        user_id="u1",
        step_index=0,
    )
    assert out.content == "ok"
    assert out.route == "cognitive_executive"
    gw.run.assert_awaited_once()
    req = gw.run.await_args[0][0]
    assert req.query == "继续上次分析"
    assert req.metadata.get("resume") is True