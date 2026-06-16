"""Data intelligence runtime tier — goal participation + V3 metadata."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.base import AgentResult


@pytest.mark.asyncio
async def test_run_data_intelligence_turn_records_goal_participation():
    from services.data_intelligence_runtime import run_data_intelligence_turn

    request = MagicMock()
    request.query = "KPI 同比为什么下降"
    request.session_id = "sess-di-1"
    request.user_id = "u1"
    request.metadata = {"request_id": "req-di-1", "goal_graph": {"root_goal_id": "goal-di-root"}}

    ctx = MagicMock()
    ctx.session_id = "sess-di-1"
    ctx.metadata = {"goal_graph": {"root_goal_id": "goal-di-root"}, "request_id": "req-di-1"}
    ctx.query = request.query

    fake_agent = MagicMock()
    fake_agent.agent_type = "data"
    fake_result = AgentResult(
        task_id="req-di-1",
        agent_type="data",
        status="success",
        content="销售额下降 10%",
        confidence=0.85,
        metadata={"sql": "SELECT 1", "row_count": 5},
    )

    with patch("kernel.runtime.capability.capability_registry.get_agent", return_value=fake_agent):
        with patch(
            "kernel.agent_runtime.executor.agent_runtime_executor.execute_task",
            new_callable=AsyncMock,
        ) as mock_exec:
            from kernel.agent_runtime.contribution import contribution_from_agent_result

            mock_exec.return_value = contribution_from_agent_result(
                fake_result,
                goal_id="goal-di-root",
                goal_description=request.query,
            )
            with patch(
                "kernel.agent_runtime.executor.agent_runtime_executor.contribution_to_agent_result",
                return_value=fake_result,
            ):
                out = await run_data_intelligence_turn(request, ctx)

    assert getattr(out, "answer", "") or out.metadata.get("data_intelligence_turn")
    assert ctx.metadata.get("goal_participation")
    assert ctx.metadata.get("agent_runtime_v3") is True
    assert out.metadata.get("data_intelligence")