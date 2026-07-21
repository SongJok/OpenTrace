"""Resume turn — RuntimeGateway path (no legacy CognitiveOrchestrator)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_resume_turn_via_gateway_builds_kernel_request():
    from kernel.runtime.resume_turn import resume_turn_via_gateway

    mock_db = AsyncMock()
    mock_log = MagicMock()
    mock_log.query = "repeat this"
    mock_log.execution_graph_json = '{"route":"kernel"}'

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_log]
    mock_db.execute = AsyncMock(return_value=mock_result)

    gw_response = MagicMock()
    gw_response.content = "ok"
    gw_response.route = "cognitive_executive"
    gw_response.validation_score = 0.9
    gw_response.passed_validation = True
    gw_response.intent_category = "qa"
    gw_response.metadata = {"resume": True}
    gw_response.result_refs = []

    with patch(
        "kernel.runtime_gateway.get_runtime_gateway",
    ) as mock_gw:
        mock_gw.return_value.run = AsyncMock(return_value=gw_response)
        out = await resume_turn_via_gateway(
            mock_db,
            session_id="s1",
            user_id="u1",
            step_index=0,
        )
    assert out.content == "ok"
    call_req = mock_gw.return_value.run.await_args[0][0]
    assert call_req.query == "repeat this"
    assert call_req.metadata.get("resume") is True


@pytest.mark.asyncio
async def test_load_resume_context_raises_without_query():
    from kernel.runtime.resume_turn import load_resume_context_from_trace

    mock_db = AsyncMock()
    mock_log = MagicMock()
    mock_log.query = ""
    mock_log.execution_graph_json = None
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_log]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="no query"):
        await load_resume_context_from_trace(mock_db, session_id="s1", step_index=0)