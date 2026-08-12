from pathlib import Path

from gateway.api_gateway.routers.documents import _merge_ingest_metadata
from infra.storage.models import Document, KnowledgeCompilationJob, KnowledgeSource

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_scope_is_first_class_on_document_and_compiled_assets():
    for model in (Document, KnowledgeSource, KnowledgeCompilationJob):
        assert "tenant_id" in model.__table__.columns
        assert "workspace_id" in model.__table__.columns


def test_ingest_preserves_review_policy_and_workspace_metadata():
    metadata = _merge_ingest_metadata(
        '{"publish_policy":"review","workspace_id":"workspace-old"}',
        {"owner": "u1", "tags": ["document"]},
    )

    assert metadata["publish_policy"] == "review"
    assert metadata["workspace_id"] == "workspace-old"
    assert metadata["owner"] == "u1"


def test_knowledge_governance_reuses_unified_ingestion_and_review_lifecycle():
    page = (ROOT / "frontend/src/pages/KnowledgeCenterPage.tsx").read_text(encoding="utf-8")
    documents_page = (ROOT / "frontend/src/pages/DocumentsPage.tsx").read_text(encoding="utf-8")
    documents = (ROOT / "gateway/api_gateway/routers/documents.py").read_text(encoding="utf-8")
    assert "apiUploadDocument" not in page
    assert "apiUploadDocument" in documents_page
    assert "我的资料" in documents_page and "投稿企业知识库" in documents_page
    assert "apiOrchestrateKnowledge" in page
    assert "apiGetKnowledgeGraph" in page
    assert "apiDecideKnowledgeReview" in page
    assert "apiPublishKnowledgePage" not in page
    assert "审核并发布" in page
    assert "window.setInterval" in page
    assert "mockGraph" not in page
    assert "实体图谱" in page and "依赖关系" in page and "来源网络" in page
    ingest_service = (ROOT / "services/document_ingestion.py").read_text(encoding="utf-8")
    assert "**existing_metadata" in ingest_service
    assert "_merge_ingest_metadata = document_ingestion.merge_ingest_metadata" in documents
    assert "background_tasks.add_task(enqueue_document_compile" not in documents


def test_worker_reconciles_uploads_and_main_rag_receives_workspace_scope():
    jobs = (ROOT / "knowledge/jobs.py").read_text(encoding="utf-8")
    runner = (ROOT / "kernel/agent_loop/runner.py").read_text(encoding="utf-8")
    rag = (ROOT / "agents/rag_agent.py").read_text(encoding="utf-8")
    assert "reconcile_ready_documents()" in jobs
    assert "KNOWLEDGE_RECONCILE_SECONDS" in jobs
    assert 'hydrated["workspace_id"] = response.workspace_id' in runner
    assert "agent_params.setdefault(" in runner
    assert '"sources", ["knowledge", "documents", "semantic_memory"]' in runner
    assert '"workspace_id": workspace_id' in rag


def test_project_knowledge_migration_is_current_head():
    migration = (ROOT / "alembic/versions/20260727_project_knowledge_scope.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision = "20260726_user_memory_score"' in migration
    assert "knowledge_sources" in migration
    assert "knowledge_compilation_jobs" in migration
