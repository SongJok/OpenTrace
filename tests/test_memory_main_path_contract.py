from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from gateway.api_gateway.routers.memories import _validated_scope_id
from infra.errors import AppException


@pytest.mark.asyncio
async def test_user_memory_scope_rejects_scope_id() -> None:
    db = AsyncMock()

    with pytest.raises(AppException):
        await _validated_scope_id(
            db,
            scope_type="user",
            scope_id="must-not-be-set",
            user_id="user-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
        )

    db.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_memory_scope_requires_owned_project() -> None:
    db = AsyncMock()
    db.scalar.return_value = None

    with pytest.raises(AppException):
        await _validated_scope_id(
            db,
            scope_type="project",
            scope_id="project-1",
            user_id="user-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
        )


@pytest.mark.asyncio
async def test_conversation_memory_scope_accepts_owned_conversation() -> None:
    db = AsyncMock()
    db.scalar.return_value = "conversation-1"

    scope_id = await _validated_scope_id(
        db,
        scope_type="conversation",
        scope_id="conversation-1",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
    )

    assert scope_id == "conversation-1"


def test_memory_e2e_covers_cross_conversation_and_isolation() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts/verify_memory_e2e.sh").read_text(
        encoding="utf-8"
    )

    assert "用户记忆跨会话召回" in source
    assert "禁用模式与临时会话隔离" in source
    assert "会话记忆隔离与级联清理" in source
    assert "Project 记忆隔离" in source
    assert "对话自动学习与新会话召回" in source
    assert "无需明确指令的主动学习与跨会话召回" in source
    assert "敏感信息与一次性请求不会持久化" in source
    assert "冲突记忆替代与旧值失效" in source
    assert "无需记住指令的明确纠正会替代旧记忆" in source


def test_rag_memory_retrieval_keeps_runtime_scope_and_lifecycle_filters() -> None:
    root = Path(__file__).resolve().parents[1]
    rag = (root / "agents/rag_agent.py").read_text(encoding="utf-8")
    runner = (root / "kernel/agent_loop/runner.py").read_text(encoding="utf-8")

    for clause in (
        "UserMemory.tenant_id == tenant_id",
        "UserMemory.workspace_id == workspace_id",
        'UserMemory.status == "active"',
        "UserMemory.expires_at > now",
        'UserMemory.scope_type == "conversation"',
        'UserMemory.scope_type == "project"',
    ):
        assert clause in rag
    assert 'hydrated["memory_enabled"]' in runner
    assert 'hydrated["memory_project_only"]' in runner


def test_confirmed_memory_prompt_requires_direct_answers() -> None:
    root = Path(__file__).resolve().parents[1]
    platform_prompt = (root / "kernel/agent_loop/prompt.py").read_text(encoding="utf-8")
    context = (root / "kernel/agent_loop/context.py").read_text(encoding="utf-8")

    assert "应依据记忆直接回答" in platform_prompt
    assert "不要声称未找到" in context
