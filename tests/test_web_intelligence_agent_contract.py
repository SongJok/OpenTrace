"""Web Intelligence cognitive agent."""

from __future__ import annotations

import pytest

from agents.base import TaskMessage
from agents.web_intelligence_agent import WebIntelligenceAgent


@pytest.mark.asyncio
async def test_web_intelligence_cognitive_trace(monkeypatch):
    async def fake_exec(*_a, **_k):
        return '{"items":[{"title":"t","snippet":"s","url":"http://x"}]}'

    async def _fake_by_name(self, **kw):
        return await fake_exec()

    monkeypatch.setattr(
        "agents.web_intelligence_agent.ToolRouter.execute_by_name",
        _fake_by_name,
    )

    agent = WebIntelligenceAgent()
    task = TaskMessage(task_id="t1", agent_type="web_intelligence", query="news")
    result = await agent.execute(task)
    assert result.status == "success"
    assert result.metadata.get("web_intelligence") is True
    assert "evidence_graph" in result.metadata
    assert "rag_evidence_intelligence" in result.metadata
    assert result.metadata["rag_evidence_intelligence"].get("source_kind") == "web"
    assert "perception" in (result.agent_trace or {})