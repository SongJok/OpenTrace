"""finalize_turn — async quota consume when event loop is running."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_post_turn_uses_async_quota_when_loop_running():
    from kernel.runtime.finalize_turn import post_turn_enterprise_accounting

    req = MagicMock()
    req.session_id = "s1"
    req.user_id = "u1"
    req.metadata = {"tenant_id": "default", "estimated_cost": 0.1}

    mock_cp = MagicMock()
    mock_cp.consume_turn_quota_async = AsyncMock(return_value=MagicMock(allowed=True))

    with patch(
        "control_plane.control_plane.get_enterprise_control_plane",
        return_value=mock_cp,
    ):
        with patch("tenant.usage_metering.get_usage_metering") as um:
            um.return_value.record_turn = MagicMock()
            post_turn_enterprise_accounting(req, None)
            await asyncio.sleep(0.05)

    mock_cp.consume_turn_quota_async.assert_called_once()
    mock_cp.consume_turn_quota.assert_not_called()


def test_data_success_evidence_objects_non_empty():
    from agents.data_agent_v2.turn_metadata import build_data_success_evidence_objects

    objs = build_data_success_evidence_objects(
        task_id="t1",
        sql="SELECT 1",
        rows=[{"x": 1}],
        confidence=0.9,
        elapsed_ms=100,
        verification_report={"status": "pass"},
        evidence_dicts=[{"source": "data_query", "source_type": "sql", "payload": {}}],
    )
    assert len(objs) >= 1
    from kernel.agent_runtime.contribution import contribution_from_agent_result
    from agents.base import AgentResult

    res = AgentResult(
        task_id="t1",
        agent_type="data",
        status="success",
        content="ok",
        confidence=0.9,
        evidence_objects=objs,
    )
    contrib = contribution_from_agent_result(res, goal_id="g1")
    assert len(contrib.unified_evidence) >= 1