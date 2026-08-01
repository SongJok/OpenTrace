from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import Request

from gateway.api_gateway.routers.skills import (
    SkillSessionBindingRequest,
    bind_session_skills,
    get_session_skills,
)
from infra.errors import AppException


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "raw_path": b"/test",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
            "scheme": "http",
        }
    )


@pytest.fixture(autouse=True)
def _disable_tenant_registration(monkeypatch):
    monkeypatch.setattr(
        "gateway.api_gateway.tenant_middleware.ensure_tenant_registered",
        lambda *_args, **_kwargs: None,
    )


@pytest.mark.asyncio
async def test_binding_is_persisted_on_owned_session():
    session = SimpleNamespace(enabled_skills=[], disabled_skills=[])
    result = Mock()
    result.scalar_one_or_none.return_value = session
    db = AsyncMock()
    db.execute.return_value = result

    response = await bind_session_skills(
        SkillSessionBindingRequest(
            session_id="s1",
            enabled_skills=["b", "a", "a"],
            disabled_skills=["old"],
        ),
        request=_request(),
        current_user=SimpleNamespace(id="u1"),
        db=db,
    )

    assert session.enabled_skills == ["a", "b"]
    assert session.disabled_skills == ["old"]
    assert response["enabled_skills"] == ["a", "b"]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_binding_is_loaded_from_database_session():
    session = SimpleNamespace(enabled_skills=["a"], disabled_skills=["old"])
    result = Mock()
    result.scalar_one_or_none.return_value = session
    db = AsyncMock()
    db.execute.return_value = result

    response = await get_session_skills(
        "s1",
        request=_request(),
        current_user=SimpleNamespace(id="u1"),
        db=db,
    )

    assert response == {
        "session_id": "s1",
        "enabled_skills": ["a"],
        "disabled_skills": ["old"],
    }


@pytest.mark.asyncio
async def test_installed_account_skill_can_be_powered_on_for_owned_session():
    installed_skill_id = "acct-123-debugging-agent@1.0.0"
    session = SimpleNamespace(
        tenant_id="default",
        workspace_id="default",
        enabled_skills=[],
        disabled_skills=[],
    )
    session_result = Mock()
    session_result.scalar_one_or_none.return_value = session
    allowed_result = Mock()
    allowed_result.scalars.return_value.all.return_value = [installed_skill_id]
    db = AsyncMock()
    db.execute.side_effect = [session_result, allowed_result]

    response = await bind_session_skills(
        SkillSessionBindingRequest(
            session_id="session-1",
            enabled_skills=[installed_skill_id],
            disabled_skills=[],
        ),
        request=_request(),
        current_user=SimpleNamespace(id="user-1"),
        db=db,
    )

    assert response["enabled_skills"] == [installed_skill_id]
    assert session.enabled_skills == [installed_skill_id]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_binding_rejects_session_outside_request_tenant_workspace():
    result = Mock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = result

    with pytest.raises(AppException, match="Session not found"):
        await bind_session_skills(
            SkillSessionBindingRequest(session_id="foreign-session"),
            request=_request(),
            current_user=SimpleNamespace(id="user-1"),
            db=db,
        )

    sql = str(db.execute.await_args.args[0])
    assert "chat_sessions.tenant_id" in sql
    assert "chat_sessions.workspace_id" in sql


@pytest.mark.asyncio
async def test_get_session_binding_is_scoped_to_request_tenant_workspace():
    result = Mock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = result

    with pytest.raises(AppException, match="Session not found"):
        await get_session_skills(
            "foreign-session",
            request=_request(),
            current_user=SimpleNamespace(id="user-1"),
            db=db,
        )

    sql = str(db.execute.await_args.args[0])
    assert "chat_sessions.user_id" in sql
    assert "chat_sessions.tenant_id" in sql
    assert "chat_sessions.workspace_id" in sql


@pytest.mark.asyncio
async def test_company_skill_binding_rejects_classification_above_clearance(monkeypatch):
    from gateway.api_gateway.routers import skills

    runtime_id = "company-secret@1.0.0"
    session = SimpleNamespace(enabled_skills=[], disabled_skills=[])
    session_result = Mock()
    session_result.scalar_one_or_none.return_value = session
    company_result = Mock()
    company_result.scalars.return_value.all.return_value = [
        SimpleNamespace(runtime_id=runtime_id, classification="confidential")
    ]
    db = AsyncMock()
    db.execute.side_effect = [session_result, company_result]
    monkeypatch.setattr(
        skills,
        "resolve_access_context",
        AsyncMock(return_value=SimpleNamespace(clearance="internal")),
    )

    with pytest.raises(AppException, match="当前企业无权启用该 Skill"):
        await bind_session_skills(
            SkillSessionBindingRequest(
                session_id="session-1",
                enabled_skills=[runtime_id],
            ),
            request=_request(),
            current_user=SimpleNamespace(id="user-1"),
            db=db,
        )

    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_runtime_uses_server_session_allowlist_when_request_sends_empty_list(
    monkeypatch,
):
    from infra.storage import database
    from kernel.agent_loop.runner import AgentLoop

    installed_skill_id = "acct-123-debugging-agent@1.0.0"
    session = SimpleNamespace(
        enabled_skills=[installed_skill_id],
        disabled_skills=[],
    )
    allowed_result = Mock()
    allowed_result.scalars.return_value.all.return_value = [installed_skill_id]

    class ScopeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _model, _identifier):
            return session

        async def scalar(self, _statement):
            return session

        async def execute(self, _statement):
            return allowed_result

    monkeypatch.setattr(database, "AsyncSessionLocal", ScopeSession)
    response = SimpleNamespace(
        conversation_id="session-1",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        request_payload={"opentrace": {"enabled_skills": []}},
    )

    params, error = await AgentLoop()._hydrate_agent_params(
        response=response,
        agent_name="skills",
        params={},
    )

    assert error is None
    assert params["enabled_skills"] == [installed_skill_id]


@pytest.mark.asyncio
async def test_agent_runtime_filters_legacy_company_binding_by_current_clearance(monkeypatch):
    from infra.storage import database
    from infra.storage.models import ChatSession, User
    from kernel.agent_loop import context
    from kernel.agent_loop.runner import AgentLoop

    internal_id = "company-internal@1.0.0"
    confidential_id = "company-confidential@1.0.0"
    session = SimpleNamespace(
        enabled_skills=[internal_id, confidential_id],
        disabled_skills=[],
    )
    user = SimpleNamespace(id="user-1", is_superuser=False)
    company_result = Mock()
    company_result.scalars.return_value.all.return_value = [
        SimpleNamespace(runtime_id=internal_id, classification="internal"),
        SimpleNamespace(runtime_id=confidential_id, classification="confidential"),
    ]

    class ScopeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, model, _identifier):
            if model is ChatSession:
                return session
            if model is User:
                return user
            return None

        async def scalar(self, _statement):
            return session

        async def execute(self, _statement):
            return company_result

    monkeypatch.setattr(database, "AsyncSessionLocal", ScopeSession)
    monkeypatch.setattr(
        context,
        "resolve_access_context",
        AsyncMock(return_value=SimpleNamespace(clearance="internal")),
    )
    response = SimpleNamespace(
        conversation_id="session-1",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        request_payload={"opentrace": {}},
    )

    params, error = await AgentLoop()._hydrate_agent_params(
        response=response,
        agent_name="skills",
        params={"enabled_skills": [confidential_id]},
    )

    assert error is None
    assert params["enabled_skills"] == [internal_id]


def test_skill_binding_migration_is_chained():
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "alembic/versions/20260711_chat_session_skills.py"
    source = path.read_text(encoding="utf-8")
    assert 'down_revision = "20260710_data_sources_tenant"' in source
    assert 'if "enabled_skills" not in columns' in source
    assert 'if "disabled_skills" not in columns' in source
