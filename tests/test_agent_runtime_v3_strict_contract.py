"""Agent Runtime V3 strict flags — staging profile and executor enforcement."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.base import AgentResult, TaskMessage
from kernel.agent_runtime.contribution import contribution_from_agent_result
from kernel.agent_runtime.executor import AgentRuntimeExecutor


def test_staging_profile_forces_v3_strict_flags():
    from infra.config.settings import Settings

    s = Settings(
        app_env="staging",
        gateway_port=14100,
        app_port=14100,
        app_secret_key="test-app-secret",
        jwt_secret="test-jwt-secret",
        data_secret_key="test-data-secret",
    )
    assert s.kernel_agent_runtime_v3_strict is True
    assert s.kernel_unified_evidence_strict is True


def test_development_defaults_soft_strict():
    from infra.config.settings import Settings

    s = Settings(app_env="development")
    assert s.kernel_agent_runtime_v3_strict is False
    assert s.kernel_unified_evidence_strict is False


def test_validate_contribution_missing_unified_when_strict():
    from infra.config.settings import settings

    with patch.object(settings, "kernel_unified_evidence_strict", True):
        from kernel.agent_runtime.executor import agent_runtime_executor

        contrib = contribution_from_agent_result(
            AgentResult(
                task_id="t",
                agent_type="tool",
                status="success",
                content="ok",
                confidence=0.9,
            ),
            goal_id="g1",
        )
        contrib.unified_evidence = []
        violations = agent_runtime_executor.validate_contribution(contrib)
        assert "missing_unified_evidence" in violations


@pytest.mark.asyncio
async def test_execute_task_raises_on_strict_violation():
    from infra.config.settings import settings

    class _Agent:
        agent_type = "tool"

        async def execute(self, task: TaskMessage) -> AgentResult:
            return AgentResult(
                task_id=task.task_id,
                agent_type="tool",
                status="success",
                content="",
                confidence=0.5,
            )

    ex = AgentRuntimeExecutor()
    task = TaskMessage(task_id="t1", agent_type="tool", query="x")

    with patch.object(settings, "kernel_agent_runtime_v3_strict", True):
        with patch.object(settings, "kernel_unified_evidence_strict", False):
            with pytest.raises(RuntimeError, match="agent_contribution_contract_violation"):
                await ex.execute_task(_Agent(), task, goal_id="g1")


@pytest.mark.asyncio
async def test_execute_task_succeeds_with_evidence_objects():
    from infra.config.settings import settings
    from kernel.runtime.objects import Evidence, Provenance

    class _Agent:
        agent_type = "rag"

        async def execute(self, task: TaskMessage) -> AgentResult:
            return AgentResult(
                task_id=task.task_id,
                agent_type="rag",
                status="success",
                content="answer",
                confidence=0.85,
                evidence_objects=[
                    Evidence(
                        content="chunk",
                        provenance=Provenance(source="rag", source_type="agent", confidence=0.8),
                        credibility_score=0.8,
                    )
                ],
            )

    ex = AgentRuntimeExecutor()
    task = TaskMessage(task_id="t2", agent_type="rag", query="docs")

    with patch.object(settings, "kernel_agent_runtime_v3_strict", True):
        with patch.object(settings, "kernel_unified_evidence_strict", True):
            contrib = await ex.execute_task(_Agent(), task, goal_id="g2")
            assert contrib.content == "answer"
            assert len(contrib.unified_evidence) >= 1
