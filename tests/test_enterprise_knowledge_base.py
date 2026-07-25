from pathlib import Path

from gateway.api_gateway.main import app
from gateway.api_gateway.routers.knowledge_enterprise import (
    ConnectorPushRequest,
    KnowledgeSpaceCreate,
)
from infra.storage.models import (
    KnowledgeConnector,
    KnowledgePrincipalMembership,
    KnowledgeReviewTask,
    KnowledgeSource,
    KnowledgeSourcePermission,
    KnowledgeSpace,
    KnowledgeSpaceMember,
    KnowledgeSpaceProject,
    KnowledgeSyncItem,
    KnowledgeSyncRun,
)
from knowledge.access import (
    CLASSIFICATION_RANK,
    SPACE_ROLE_RANK,
    KnowledgeAccessContext,
    accessible_source_predicate,
    classification_allows,
    role_allows,
)
from services.rag_query_planning import build_rag_query_plan, normalize_rag_evidence

ROOT = Path(__file__).resolve().parents[1]


def test_enterprise_knowledge_models_cover_space_acl_sync_and_review() -> None:
    assert KnowledgeSpace.__tablename__ == "knowledge_spaces"
    assert {"space_type", "visibility", "publish_policy", "review_cycle_days"}.issubset(
        set(KnowledgeSpace.__table__.columns.keys())
    )
    assert {"subject_type", "subject_id", "role", "expires_at"}.issubset(
        set(KnowledgeSpaceMember.__table__.columns.keys())
    )
    assert {"principal_type", "principal_id", "source", "effective_to"}.issubset(
        set(KnowledgePrincipalMembership.__table__.columns.keys())
    )
    assert KnowledgeSpaceProject.__tablename__ == "knowledge_space_projects"
    assert {"connector_type", "credential_ref", "sync_cursor", "last_sync_at"}.issubset(
        set(KnowledgeConnector.__table__.columns.keys())
    )
    assert KnowledgeSyncRun.__tablename__ == "knowledge_sync_runs"
    assert KnowledgeSyncItem.__tablename__ == "knowledge_sync_items"
    assert {
        "run_id",
        "connector_id",
        "external_id",
        "content_hash",
        "acl_snapshot",
        "status",
        "attempts",
        "locked_by",
    }.issubset(set(KnowledgeSyncItem.__table__.columns.keys()))
    assert {"space_id", "connector_id", "classification", "effective_to", "deleted_at"}.issubset(
        set(KnowledgeSource.__table__.columns.keys())
    )
    assert KnowledgeSourcePermission.__tablename__ == "knowledge_source_permissions"
    assert {"required_role", "diff_summary", "decided_by", "decided_at"}.issubset(
        set(KnowledgeReviewTask.__table__.columns.keys())
    )


def test_space_roles_and_classification_are_monotonic() -> None:
    assert SPACE_ROLE_RANK == {
        "viewer": 1,
        "contributor": 2,
        "reviewer": 3,
        "publisher": 4,
        "admin": 5,
    }
    assert role_allows("publisher", "reviewer") is True
    assert role_allows("contributor", "publisher") is False
    assert CLASSIFICATION_RANK["restricted"] > CLASSIFICATION_RANK["confidential"]
    assert classification_allows("confidential", "internal") is True
    assert classification_allows("internal", "confidential") is False


def test_source_access_predicate_contains_space_acl_validity_and_classification() -> None:
    context = KnowledgeAccessContext(
        user_id="user-a",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        subjects=(("department", "finance"), ("user", "user-a")),
        clearance="confidential",
        space_roles={"space-a": "viewer"},
    )
    sql = str(accessible_source_predicate(context, project_id="project-a"))
    for expected in (
        "knowledge_sources.owner_id",
        "knowledge_sources.space_id",
        "knowledge_source_permissions",
        "knowledge_sources.deleted_at",
        "knowledge_sources.effective_to",
        "knowledge_sources.classification",
        "knowledge_space_projects",
    ):
        assert expected in sql


def test_enterprise_knowledge_openapi_exposes_employee_and_governance_surfaces() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/knowledge/spaces": {"get", "post"},
        "/api/v1/knowledge/spaces/{space_id}/members": {"get", "post"},
        "/api/v1/knowledge/spaces/{space_id}/sources": {"get"},
        "/api/v1/knowledge/spaces/{space_id}/assets": {"get"},
        "/api/v1/knowledge/connectors": {"get", "post"},
        "/api/v1/knowledge/connectors/{connector_id}/push": {"post"},
        "/api/v1/knowledge/sync-runs": {"get"},
        "/api/v1/knowledge/sync-runs/{run_id}/items": {"get"},
        "/api/v1/knowledge/sync-runs/{run_id}/retry": {"post"},
        "/api/v1/knowledge/reviews": {"get"},
        "/api/v1/knowledge/reviews/{review_id}/decision": {"post"},
        "/api/v1/knowledge/search": {"post"},
    }
    for path, methods in expected.items():
        assert methods.issubset(paths[path])

    push_operation = paths["/api/v1/knowledge/connectors/{connector_id}/push"]["post"]
    assert "202" in push_operation["responses"]


def test_space_and_connector_requests_enforce_enterprise_limits() -> None:
    space = KnowledgeSpaceCreate(name="公司制度", space_type="company")
    assert space.publish_policy == "review"
    assert space.default_classification == "internal"
    push = ConnectorPushRequest.model_validate(
        {
            "cursor": "delta-2",
            "snapshots": [
                {
                    "external_id": "policy-1",
                    "title": "报销制度",
                    "content": "差旅报销需要直属主管审批。",
                    "classification": "internal",
                    "acl": [
                        {
                            "subject_type": "department",
                            "subject_id": "finance",
                            "permission": "view",
                        }
                    ],
                }
            ],
        }
    )
    assert push.cursor == "delta-2"
    assert push.snapshots[0].acl[0].subject_type == "department"


def test_rag_evidence_keeps_enterprise_governance_context() -> None:
    plan = build_rag_query_plan(
        raw_query="报销制度",
        normalized_query="报销制度",
        rewritten_query="报销制度",
        query_type="factual",
        hints=[],
        query_terms=["报销", "制度"],
        sources=["knowledge"],
        top_k=5,
        llmwiki_top_k=2,
        min_score=0.3,
        user_id="u1",
        tenant_id="t1",
        workspace_id="w1",
    )
    evidence = normalize_rag_evidence(
        {
            "id": "claim-1",
            "source_type": "knowledge_claim",
            "text": "差旅报销需要直属主管审批。",
            "score": 0.8,
            "space_id": "space-1",
            "classification": "internal",
            "source_system": "sharepoint",
            "sync_status": "current",
            "effective_from": "2026-07-01T00:00:00+00:00",
            "review_due_at": "2027-01-01T00:00:00+00:00",
        },
        plan=plan,
    )
    assert evidence["space_id"] == "space-1"
    assert evidence["classification"] == "internal"
    assert evidence["source_system"] == "sharepoint"
    assert evidence["sync_status"] == "current"


def test_governed_migration_and_local_alembic_template_are_present() -> None:
    migration = (ROOT / "alembic/versions/r0001_enterprise_knowledge_base.py").read_text()
    assert 'revision = "r0001_enterprise_knowledge_base"' in migration
    assert 'down_revision = "20260803_chatgpt_five_pillars"' in migration
    for table in (
        "knowledge_spaces",
        "knowledge_space_members",
        "knowledge_principal_memberships",
        "knowledge_connectors",
        "knowledge_sync_runs",
        "knowledge_source_permissions",
        "knowledge_review_tasks",
    ):
        assert table in migration
    assert (ROOT / "alembic/script.py.mako").exists()


def test_frontend_separates_employee_knowledge_base_from_governance_console() -> None:
    page = (ROOT / "frontend/src/pages/EnterpriseKnowledgePage.tsx").read_text()
    app = (ROOT / "frontend/src/App.tsx").read_text()
    sidebar = (ROOT / "frontend/src/components/Sidebar.tsx").read_text()
    client = (ROOT / "frontend/src/api/client.ts").read_text()
    assert "企业知识库" in page
    assert "知识资产" in page and "来源与时效" in page and "发布审核" in page
    assert "同步运行记录" in page and "重试失败项" in page
    assert 'path="/knowledge-base"' in app
    assert "企业知识库" in sidebar and "知识治理" in sidebar
    assert "apiSearchEnterpriseKnowledge" in client
    assert "apiListKnowledgeSyncRuns" in client
    assert "apiRetryKnowledgeSyncRun" in client
    assert "knowledge_space_id" in client


def test_durable_sync_worker_is_wired_before_compilation() -> None:
    jobs = (ROOT / "knowledge/jobs.py").read_text()
    sync = (ROOT / "knowledge/sync.py").read_text()
    assert "process_pending_sync_items" in jobs
    assert jobs.index("process_pending_sync_items") < jobs.index("process_pending_compile_jobs()")
    assert ".with_for_update(skip_locked=True)" in sync
    assert "await enqueue_document_compile(document.id)" in sync
    assert 'if key == "batch_hash"' in sync
    assert "blocking_earlier_run" in sync
    assert "knowledge_sync_worker_lease_expired" in sync


def test_durable_sync_migration_is_additive_and_reversible() -> None:
    migration = (ROOT / "alembic/versions/r0002_durable_knowledge_sync_queue.py").read_text()
    assert 'revision = "r0002_durable_knowledge_sync_queue"' in migration
    assert 'down_revision = "r0001_enterprise_knowledge_base"' in migration
    assert '"knowledge_sync_items"' in migration
    assert "op.create_table(" in migration
    assert 'op.drop_table("knowledge_sync_items")' in migration
