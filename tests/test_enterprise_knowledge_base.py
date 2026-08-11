from datetime import UTC, datetime, timedelta
from pathlib import Path

from gateway.api_gateway.main import app
from gateway.api_gateway.routers.knowledge_enterprise import (
    ConnectorPushRequest,
    KnowledgeSearchRequest,
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
from knowledge.domain import KnowledgeStatus, source_is_withdrawn
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
    search = KnowledgeSearchRequest(query="报销制度", space_id="space-a")
    assert search.space_id == "space-a"
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
    employee_page = (ROOT / "frontend/src/pages/EnterpriseKnowledgePage.tsx").read_text()
    governance_page = (ROOT / "frontend/src/pages/KnowledgeCenterPage.tsx").read_text()
    documents_page = (ROOT / "frontend/src/pages/DocumentsPage.tsx").read_text()
    app = (ROOT / "frontend/src/App.tsx").read_text()
    sidebar = (ROOT / "frontend/src/components/Sidebar.tsx").read_text()
    client = (ROOT / "frontend/src/api/client.ts").read_text()
    assert "企业知识库" in employee_page
    assert "知识资产" in employee_page and "来源与状态" in employee_page
    assert "apiListKnowledgeReviews" not in employee_page
    assert "apiListEnterpriseKnowledgeConnectors" not in employee_page
    assert "投稿资料" in employee_page and "/documents?space_id=" in employee_page
    assert "知识库质量中心" in governance_page
    assert "审核队列" in governance_page and "连接器与同步" in governance_page
    assert "空间访问控制" in governance_page and "重试失败项" in governance_page
    assert "我的资料" in documents_page and "投稿企业知识库" in documents_page
    assert 'path="/knowledge-base"' in app
    assert "企业知识库" in sidebar and "知识库质量中心" in sidebar
    assert "role === 'admin'" in sidebar
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


def test_knowledge_lint_uses_merge_case_id_and_compiler_rolls_back_failed_session() -> None:
    lint_source = (ROOT / "knowledge/lint.py").read_text(encoding="utf-8")
    compiler_source = (ROOT / "knowledge/compiler.py").read_text(encoding="utf-8")

    assert '"resource_id": existing_case.id' in lint_source
    assert '"resource_id": entity_key' not in lint_source
    failure_block = compiler_source.split("async def compile_document_knowledge_in_session", 1)[0]
    assert "await db.rollback()" in failure_block
    assert "await db.commit()\n            raise" not in failure_block


def test_compilation_error_persistence_never_exposes_document_or_sql_payload() -> None:
    from knowledge.jobs import _safe_compilation_error

    assert _safe_compilation_error(ValueError("knowledge_source_has_no_document")) == (
        "knowledge_source_has_no_document"
    )
    unsafe = _safe_compilation_error(RuntimeError("SELECT secret FROM document正文"))
    assert unsafe == "knowledge_compilation_failed:RuntimeError"
    assert "document" not in unsafe.lower()
    assert "正文" not in unsafe


def test_space_quality_scope_includes_only_merge_cases_inside_claim_scope() -> None:
    from types import SimpleNamespace

    from knowledge.lint import merge_case_ids_in_claim_scope

    rows = [
        SimpleNamespace(id="case-in", candidate_ids=["claim-a", "claim-b"]),
        SimpleNamespace(id="case-cross", candidate_ids=["claim-a", "claim-x"]),
        SimpleNamespace(id="case-empty", candidate_ids=[]),
    ]

    assert merge_case_ids_in_claim_scope(rows, {"claim-a", "claim-b"}) == {"case-in"}


def test_merge_resolution_archives_pages_left_without_published_claims() -> None:
    source = (ROOT / "knowledge/merge.py").read_text(encoding="utf-8")

    assert "await db.flush()" in source.split("archived_page_ids", 1)[0]
    assert 'page.status = "archived"' in source
    assert 'relation.status = "archived"' in source
    assert '"archived_page_ids": archived_page_ids' in source


def test_withdrawn_sources_require_explicit_reactivation() -> None:
    assert source_is_withdrawn(
        status=KnowledgeStatus.DEPRECATED.value,
        sync_status="current",
        deleted_at=None,
    )
    assert source_is_withdrawn(
        status=KnowledgeStatus.PUBLISHED.value,
        sync_status="deleted",
        deleted_at=None,
    )
    assert source_is_withdrawn(
        status=KnowledgeStatus.PUBLISHED.value,
        sync_status="current",
        deleted_at=object(),
    )
    assert not source_is_withdrawn(
        status=KnowledgeStatus.PUBLISHED.value,
        sync_status="current",
        deleted_at=None,
    )


def test_withdrawal_cannot_be_reversed_by_reconciliation_or_inflight_compile() -> None:
    jobs = (ROOT / "knowledge/jobs.py").read_text(encoding="utf-8")
    compiler = (ROOT / "knowledge/compiler.py").read_text(encoding="utf-8")
    lifecycle = (ROOT / "knowledge/lifecycle.py").read_text(encoding="utf-8")

    assert "source_is_withdrawn(" in jobs
    assert '"reason": "source_withdrawn"' in jobs
    assert ".with_for_update()" in jobs
    assert "source_is_withdrawn(" in compiler
    assert '"reason": "source_withdrawn"' in compiler
    assert ".with_for_update()" in compiler
    assert "await db.refresh(source, with_for_update=True)" in lifecycle
    assert 'KnowledgeCompilationJob.status.in_(["pending", "running"])' in lifecycle
    assert '"reason": "source_withdrawn"' in lifecycle


def test_push_connector_is_not_marked_stale_without_periodic_events() -> None:
    from knowledge.governance import connector_sync_is_stale

    now = datetime(2026, 7, 27, 8, 0, tzinfo=UTC)
    old_activity = now - timedelta(hours=2)
    assert not connector_sync_is_stale(
        connector_type="push",
        status="active",
        sync_interval_seconds=900,
        last_sync_at=old_activity,
        created_at=old_activity,
        now=now,
    )
    assert connector_sync_is_stale(
        connector_type="confluence",
        status="active",
        sync_interval_seconds=900,
        last_sync_at=old_activity,
        created_at=old_activity,
        now=now,
    )
    assert not connector_sync_is_stale(
        connector_type="confluence",
        status="failed",
        sync_interval_seconds=900,
        last_sync_at=old_activity,
        created_at=old_activity,
        now=now,
    )


def test_governance_health_counts_merge_case_lint_in_the_same_space_scope() -> None:
    governance = (ROOT / "knowledge/governance.py").read_text(encoding="utf-8")

    assert "scoped_merge_case_ids = merge_case_ids_in_claim_scope" in governance
    assert "| scoped_merge_case_ids" in governance
    assert '"open_merge_cases": len(scoped_merge_case_ids)' in governance
