from pathlib import Path

from infra.storage.models import Document, KnowledgeCompilationJob, KnowledgeSource


ROOT = Path(__file__).resolve().parents[1]


def test_project_scope_is_first_class_on_document_and_compiled_assets():
    assert "project_id" in Document.__table__.columns
    assert "project_id" in KnowledgeSource.__table__.columns
    assert "project_id" in KnowledgeCompilationJob.__table__.columns


def test_knowledge_page_is_connected_to_real_upload_jobs_and_networks():
    page = (ROOT / "frontend/src/pages/KnowledgeCenterPage.tsx").read_text(encoding="utf-8")
    assert "apiUploadDocument" in page
    assert "apiOrchestrateKnowledge" in page
    assert "apiGetKnowledgeGraph" in page
    assert "mockGraph" not in page
    assert "实体图谱" in page and "依赖关系" in page and "来源网络" in page


def test_worker_reconciles_uploads_and_main_rag_receives_project_scope():
    jobs = (ROOT / "knowledge/jobs.py").read_text(encoding="utf-8")
    runner = (ROOT / "kernel/agent_loop/runner.py").read_text(encoding="utf-8")
    rag = (ROOT / "agents/rag_agent.py").read_text(encoding="utf-8")
    assert "reconcile_ready_documents()" in jobs
    assert "KNOWLEDGE_RECONCILE_SECONDS" in jobs
    assert 'hydrated["project_id"] = project_id' in runner
    assert 'agent_params.setdefault("sources", ["knowledge", "documents", "semantic_memory"])' in runner
    assert 'retrieval_scope["project_id"] = project_id' in rag


def test_project_knowledge_migration_is_current_head():
    migration = (ROOT / "alembic/versions/20260727_project_knowledge_scope.py").read_text(encoding="utf-8")
    assert 'down_revision = "20260726_user_memory_score"' in migration
    assert "knowledge_sources" in migration
    assert "knowledge_compilation_jobs" in migration
