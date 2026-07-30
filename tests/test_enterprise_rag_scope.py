from types import SimpleNamespace

import pytest

from agents.base import TaskMessage
from agents.rag_agent import RagAgent
from kernel.agent_loop.runner import AgentLoop
from knowledge.access import KnowledgeAccessContext
from knowledge.query import search_knowledge


class _EmptyRows:
    def all(self):
        return []


class _FakeKnowledgeSession:
    def __init__(self) -> None:
        self.statements = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, model, key):
        return SimpleNamespace(id=key, is_superuser=False)

    async def execute(self, statement):
        self.statements.append(statement)
        return _EmptyRows()


@pytest.mark.asyncio
async def test_search_knowledge_intersects_multiple_spaces_with_user_acl(monkeypatch):
    session = _FakeKnowledgeSession()

    async def fake_access_context(*args, **kwargs):
        return KnowledgeAccessContext(
            user_id="user-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            subjects=(("user", "user-1"),),
            clearance="internal",
            space_roles={"space-company": "viewer", "space-department": "viewer"},
        )

    monkeypatch.setattr("knowledge.query.AsyncSessionLocal", lambda: session)
    monkeypatch.setattr("knowledge.query.resolve_access_context", fake_access_context)

    result = await search_knowledge(
        query="公司报销制度",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        knowledge_space_ids=["space-company", "space-denied", "space-company"],
        top_k=5,
    )

    assert result == []
    assert session.statements
    compiled = [statement.compile() for statement in session.statements]
    assert all("knowledge_sources.space_id IN" in str(statement) for statement in compiled)
    assert all(
        ["space-company"]
        in [value for value in statement.params.values() if isinstance(value, list)]
        for statement in compiled
    )
    assert all("space-denied" not in str(statement.params) for statement in compiled)


@pytest.mark.asyncio
async def test_search_knowledge_explicit_empty_space_scope_fails_closed(monkeypatch):
    session = _FakeKnowledgeSession()

    async def fake_access_context(*args, **kwargs):
        return KnowledgeAccessContext(
            user_id="user-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            subjects=(("user", "user-1"),),
            clearance="restricted",
            space_roles={"space-company": "viewer"},
        )

    monkeypatch.setattr("knowledge.query.AsyncSessionLocal", lambda: session)
    monkeypatch.setattr("knowledge.query.resolve_access_context", fake_access_context)

    result = await search_knowledge(
        query="公司制度",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        knowledge_space_ids=[],
        top_k=5,
    )

    assert result == []
    assert session.statements == []


@pytest.mark.asyncio
async def test_enterprise_grounding_uses_only_trusted_knowledge_spaces(monkeypatch):
    calls = []

    async def fake_search_knowledge(**kwargs):
        calls.append(kwargs)
        return [
            {
                "id": "claim-1",
                "source_type": "knowledge_claim",
                "title": "公司报销制度",
                "text": "公司报销应在费用发生后 30 天内提交。",
                "score": 0.92,
                "space_id": "space-company",
                "source_id": "source-1",
                "source_version_id": "version-1",
                "claim_id": "claim-1",
                "evidence_tier": "factual",
                "disclosure_stage": "claim",
            }
        ]

    async def unexpected_document_search(*args, **kwargs):
        raise AssertionError("企业 grounding 不应触发未受空间治理的文档检索")

    monkeypatch.setattr("agents.rag_agent.search_knowledge", fake_search_knowledge)
    monkeypatch.setattr(
        "plugins.document_plugin.DocumentPlugin.search_chunks", unexpected_document_search
    )
    monkeypatch.setattr(
        "plugins.document_plugin.DocumentPlugin.search_llmwiki", unexpected_document_search
    )
    monkeypatch.setattr("agents.rag_agent.settings.rag_rerank_enabled", False)

    result = await RagAgent().execute(
        TaskMessage(
            task_id="enterprise-rag-1",
            agent_type="rag",
            query="公司的报销制度是什么？",
            user_id="user-1",
            params={
                "tenant_id": "tenant-1",
                "workspace_id": "workspace-1",
                "sources": ["documents", "semantic_memory"],
                "knowledge_space_ids": ["space-company", "space-department"],
                "enterprise_grounding_required": True,
            },
        )
    )

    assert result.status == "success"
    assert result.metadata["sources"] == ["knowledge"]
    assert calls
    assert all(
        call["knowledge_space_ids"] == ["space-company", "space-department"] for call in calls
    )
    filters = result.metadata["rag_query_plan"]["filters"]
    assert filters["knowledge_space_ids"] == ["space-company", "space-department"]
    assert filters["enterprise_grounding_required"] is True
    assert all(item["source_type"].startswith("knowledge") for item in result.metadata["chunks"])


@pytest.mark.asyncio
async def test_enterprise_grounding_empty_space_scope_has_no_fallback(monkeypatch):
    calls = []

    async def fake_search_knowledge(**kwargs):
        calls.append(kwargs)
        return []

    async def unexpected_document_search(*args, **kwargs):
        raise AssertionError("空企业空间范围不能回退到个人文档")

    monkeypatch.setattr("agents.rag_agent.search_knowledge", fake_search_knowledge)
    monkeypatch.setattr(
        "plugins.document_plugin.DocumentPlugin.search_chunks", unexpected_document_search
    )
    monkeypatch.setattr(
        "plugins.document_plugin.DocumentPlugin.search_llmwiki", unexpected_document_search
    )
    monkeypatch.setattr("agents.rag_agent.settings.rag_rerank_enabled", False)

    result = await RagAgent().execute(
        TaskMessage(
            task_id="enterprise-rag-empty",
            agent_type="rag",
            query="公司的保密制度是什么？",
            user_id="user-1",
            params={
                "tenant_id": "tenant-1",
                "workspace_id": "workspace-1",
                "sources": ["knowledge", "documents", "semantic_memory"],
                "knowledge_space_ids": [],
                "enterprise_grounding_required": True,
            },
        )
    )

    assert result.status == "success"
    assert result.metadata["sources"] == ["knowledge"]
    assert result.metadata["chunks"] == []
    assert result.metadata["quality"]["answerability_state"] == "unanswerable"
    assert calls and all(call["knowledge_space_ids"] == [] for call in calls)


@pytest.mark.asyncio
async def test_runner_replaces_model_space_scope_with_trusted_enterprise_manifest(monkeypatch):
    from infra.storage import database

    session = SimpleNamespace(
        is_temporary=False,
        assistant_profile_id=None,
    )

    class ScopeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _model, _identifier):
            return session

    monkeypatch.setattr(database, "AsyncSessionLocal", ScopeSession)
    response = SimpleNamespace(
        conversation_id="session-1",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        request_payload={"opentrace": {}},
        response_metadata={
            "enterprise_context": {
                "requires_grounding": True,
                "knowledge_space_ids": ["space-company"],
            }
        },
    )

    params, error = await AgentLoop._hydrate_agent_params(
        response=response,
        agent_name="rag",
        params={
            "space_id": "space-denied",
            "knowledge_space_ids": ["space-denied"],
            "enterprise_grounding_required": False,
        },
    )

    assert error is None
    assert "space_id" not in params
    assert params["knowledge_space_ids"] == ["space-company"]
    assert params["enterprise_grounding_required"] is True
    assert params["memory_enabled"] is False


@pytest.mark.asyncio
async def test_runner_ignores_model_enterprise_grounding_without_trusted_manifest(monkeypatch):
    from infra.storage import database

    session = SimpleNamespace(
        is_temporary=False,
        assistant_profile_id=None,
    )

    class ScopeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _model, _identifier):
            return session

    monkeypatch.setattr(database, "AsyncSessionLocal", ScopeSession)
    response = SimpleNamespace(
        conversation_id="session-1",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        request_payload={"opentrace": {"memory_mode": "disabled"}},
        response_metadata={"enterprise_context": {"requires_grounding": False}},
    )

    params, error = await AgentLoop._hydrate_agent_params(
        response=response,
        agent_name="rag",
        params={
            "knowledge_space_ids": ["space-denied"],
            "enterprise_grounding_required": True,
        },
    )

    assert error is None
    assert "knowledge_space_ids" not in params
    assert "enterprise_grounding_required" not in params
