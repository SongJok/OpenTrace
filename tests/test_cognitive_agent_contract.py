"""Cognitive Agent six-phase loop."""

from __future__ import annotations

import pytest

from agents.base import TaskMessage
from agents.cognitive_agent import PassthroughCognitiveAgent


@pytest.mark.asyncio
async def test_cognitive_agent_trace_has_six_phases():
    agent = PassthroughCognitiveAgent("test_cog")
    task = TaskMessage(task_id="t1", agent_type="test_cog", query="hello")
    result = await agent.execute(task)
    assert result.status == "success"
    trace = result.agent_trace or {}
    for phase in ("perception", "reasoning", "planning", "execution", "reflection", "learning"):
        assert phase in trace
    assert result.metadata.get("cognitive_agent") is True