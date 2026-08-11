from __future__ import annotations

from types import SimpleNamespace

import pytest

from data_agent.contracts import DataSourceDecision
from infra.security.identity import is_enterprise_admin
from infra.security.resource_scope import (
    accessible_document_predicate,
    load_scoped_conversation,
)
from infra.storage.models import KnowledgeSpace
from kernel.agent_loop.context import ContextAssembler
from kernel.agent_loop.memory_learner import MemoryLearner
from kernel.agent_loop.runner import AgentLoop
from knowledge.access import (
    KnowledgeAccessContext,
    accessible_source_predicate,
    resolve_access_context,
)
from knowledge.query import search_knowledge


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self.rows)

    def all(self):
        return list(self.rows)


def _response(**overrides):
    values = {
        "id": "resp-1",
        "conversation_id": "conversation-1",
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "request_payload": {"input": "继续", "opentrace": {}},
        "response_metadata": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_admin_semantics_cover_role_and_superuser() -> None:
    assert is_enterprise_admin(SimpleNamespace(role="admin", is_superuser=False)) is True
    assert is_enterprise_admin(SimpleNamespace(role="user", is_superuser=True)) is True
    assert is_enterprise_admin(SimpleNamespace(role="user", is_superuser=False)) is False


@pytest.mark.asyncio
async def test_admin_resolves_all_current_workspace_spaces_as_admin() -> None:
    spaces = [
        KnowledgeSpace(id="space-private", owner_id="other-1"),
        KnowledgeSpace(id="space-members", owner_id="other-2"),
    ]

    class Session:
        def __init__(self):
            self.calls = 0
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            self.calls += 1
            return _Rows() if self.calls == 1 else _Rows((space, None) for space in spaces)

    db = Session()
    context = await resolve_access_context(
        db,
        user=SimpleNamespace(id="admin-1", role="admin", is_superuser=False),
        tenant_id="tenant-1",
        workspace_id="workspace-1",
    )

    assert context.workspace_admin is True
    assert context.clearance == "restricted"
    assert context.space_roles == {"space-private": "admin", "space-members": "admin"}
    space_sql = str(db.statements[-1])
    assert "knowledge_spaces.tenant_id" in space_sql
    assert "knowledge_spaces.workspace_id" in space_sql


def test_knowledge_source_access_keeps_tenant_boundary_for_admin() -> None:
    admin = KnowledgeAccessContext(
        user_id="admin-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        subjects=(("user", "admin-1"),),
        clearance="restricted",
        space_roles={"space-private": "admin"},
        workspace_admin=True,
    )
    employee = KnowledgeAccessContext(
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        subjects=(("user", "user-1"),),
        clearance="internal",
        space_roles={"space-shared": "viewer"},
    )

    admin_sql = str(accessible_source_predicate(admin))
    employee_sql = str(accessible_source_predicate(employee))
    assert "knowledge_sources.tenant_id" in admin_sql
    assert "knowledge_sources.workspace_id" in admin_sql
    assert "knowledge_sources.owner_id" not in admin_sql
    assert "knowledge_sources.owner_id" in employee_sql
    assert "knowledge_source_permissions" in employee_sql


def test_raw_document_qna_admin_is_derived_server_side_and_scope_bounded() -> None:
    sql = str(
        accessible_document_predicate(
            user_id="admin-1",
            tenant_metadata={"tenant_id": "tenant-1", "workspace_id": "workspace-1"},
        )
    )
    assert "documents.tenant_id" in sql
    assert "documents.workspace_id" in sql
    assert "documents.owner_id" in sql
    assert "users.role" in sql
    assert "users.is_superuser" in sql
    assert str(accessible_document_predicate(user_id="shared")) == "false"


@pytest.mark.asyncio
async def test_scoped_conversation_query_uses_complete_execution_subject() -> None:
    class Session:
        statement = None

        async def scalar(self, statement):
            self.statement = statement
            return None

    db = Session()
    result = await load_scoped_conversation(
        db,
        conversation_id="conversation-1",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
    )

    assert result is None
    sql = str(db.statement)
    for column in (
        "chat_sessions.id",
        "chat_sessions.user_id",
        "chat_sessions.tenant_id",
        "chat_sessions.workspace_id",
    ):
        assert column in sql


@pytest.mark.asyncio
async def test_context_and_memory_fail_closed_on_conversation_scope_mismatch(monkeypatch) -> None:
    async def missing_session(*_args, **_kwargs):
        return None

    class Session:
        async def scalar(self, _statement):
            return None

    with pytest.raises(PermissionError, match="conversation_scope_mismatch"):
        await ContextAssembler().assemble(
            Session(),
            response=_response(),
            user_query="继续",
            request_payload={"input": "继续", "opentrace": {}},
        )

    monkeypatch.setattr(
        "kernel.agent_loop.memory_learner.load_scoped_conversation", missing_session
    )
    assert await MemoryLearner().learn(SimpleNamespace(), response=_response()) == []


@pytest.mark.asyncio
async def test_agent_param_hydration_rejects_cross_scope_conversation(monkeypatch) -> None:
    from infra.storage import database

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def scalar(self, _statement):
            return None

    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    _, error = await AgentLoop._hydrate_agent_params(
        response=_response(),
        agent_name="rag",
        params={"knowledge_space_ids": ["space-other-user"]},
    )

    assert error == {"error": "conversation_scope_mismatch"}


@pytest.mark.asyncio
async def test_data_agent_ignores_client_and_model_source_selection(monkeypatch) -> None:
    from data_agent.adapters.opentrace.source_resolution import OpenTraceSourceResolver
    from infra.storage import database

    session = SimpleNamespace(is_temporary=False, assistant_profile_id=None)

    class ScopeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def scalar(self, _statement):
            return session

    captured: dict[str, object] = {}

    async def resolve(_self, **kwargs):
        captured.update(kwargs)
        return DataSourceDecision(
            status="selected",
            question=str(kwargs["question"]),
            selected_data_source_id="trusted-source",
            selected_data_source_name="认证交易数仓",
            confidence=0.96,
            reason="命中认证指标与已验证 Schema",
        )

    monkeypatch.setattr(database, "AsyncSessionLocal", ScopeSession)
    monkeypatch.setattr(OpenTraceSourceResolver, "resolve", resolve)
    response = _response(
        request_payload={
            "input": "查询付费用户数",
            "opentrace": {
                "project_id": "client-project",
                "data_source_ids": ["client-source"],
            },
        }
    )

    params, error = await AgentLoop._hydrate_agent_params(
        response=response,
        agent_name="data",
        params={
            "project_id": "model-project",
            "data_source_id": "model-source",
            "data_source_name": "模型指定库",
            "source_decision": {"status": "selected"},
        },
        query="查询付费用户数",
    )

    assert error is None
    assert captured["project_id"] is None
    assert captured["explicit_id"] is None
    assert captured["candidate_ids"] is None
    assert params["data_source_id"] == "trusted-source"
    assert params["data_source_name"] == "认证交易数仓"
    assert params["source_decision"]["selected_data_source_id"] == "trusted-source"
    assert "project_id" not in params
    assert params["generation_only"] is True


@pytest.mark.asyncio
async def test_hot_knowledge_state_is_joined_to_current_conversation_scope(monkeypatch) -> None:
    class Session:
        def __init__(self):
            self.scalar_statements = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _model, key):
            return SimpleNamespace(id=key, role="user", is_superuser=False)

        async def scalar(self, statement):
            self.scalar_statements.append(statement)
            return None

        async def execute(self, _statement):
            return _Rows()

    session = Session()

    async def access_context(*_args, **_kwargs):
        return KnowledgeAccessContext(
            user_id="user-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            subjects=(("user", "user-1"),),
            clearance="internal",
            space_roles={},
        )

    monkeypatch.setattr("knowledge.query.AsyncSessionLocal", lambda: session)
    monkeypatch.setattr("knowledge.query.resolve_access_context", access_context)
    assert (
        await search_knowledge(
            query="报销制度",
            user_id="user-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            session_id="conversation-1",
            top_k=3,
        )
        == []
    )

    state_sql = str(session.scalar_statements[0])
    assert "JOIN chat_sessions" in state_sql
    assert "chat_sessions.user_id" in state_sql
    assert "chat_sessions.tenant_id" in state_sql
    assert "chat_sessions.workspace_id" in state_sql


@pytest.mark.asyncio
async def test_knowledge_search_without_authenticated_user_fails_closed(monkeypatch) -> None:
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _model, _key):
            return None

    monkeypatch.setattr("knowledge.query.AsyncSessionLocal", Session)
    result = await search_knowledge(
        query="薪酬制度",
        user_id="shared",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        top_k=3,
    )
    assert result == []
