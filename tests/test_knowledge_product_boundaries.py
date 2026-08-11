from pathlib import Path
from types import SimpleNamespace

from gateway.api_gateway.routers.documents import _source_requires_withdrawal

ROOT = Path(__file__).resolve().parents[1]


def test_documents_are_the_only_interactive_upload_surface() -> None:
    documents = (ROOT / "frontend/src/pages/DocumentsPage.tsx").read_text()
    employee = (ROOT / "frontend/src/pages/EnterpriseKnowledgePage.tsx").read_text()
    governance = (ROOT / "frontend/src/pages/KnowledgeCenterPage.tsx").read_text()

    assert "apiUploadDocument" in documents
    assert "仅自己使用" in documents
    assert "当前 Project" in documents
    assert "投稿企业知识库" in documents
    assert "apiUploadDocument" not in employee
    assert "apiUploadDocument" not in governance
    assert "/documents?space_id=" in employee


def test_employee_surface_excludes_governance_operations() -> None:
    employee = (ROOT / "frontend/src/pages/EnterpriseKnowledgePage.tsx").read_text()
    governance = (ROOT / "frontend/src/pages/KnowledgeCenterPage.tsx").read_text()

    for operation in (
        "apiListKnowledgeReviews",
        "apiDecideKnowledgeReview",
        "apiGrantKnowledgeSpaceMember",
    ):
        assert operation not in employee
        assert operation in governance
    assert "apiListEnterpriseKnowledgeConnectors" not in employee
    assert "apiListEnterpriseKnowledgeConnectors" not in governance


def test_governance_uses_review_task_as_enterprise_publish_entry() -> None:
    governance = (ROOT / "frontend/src/pages/KnowledgeCenterPage.tsx").read_text()
    router = (ROOT / "gateway/api_gateway/routers/knowledge.py").read_text()

    assert "apiDecideKnowledgeReview" in governance
    assert "apiPublishKnowledgePage" not in governance
    assert "企业知识版本必须通过审核任务发布" in router


def test_document_delete_preserves_governed_lineage() -> None:
    router = (ROOT / "gateway/api_gateway/routers/documents.py").read_text()

    assert "protected_sources" in router
    assert "该资料已进入企业知识治理" in router
    assert "source.active_version_id" in router
    assert 'source.status in {"review", "published", "deprecated"}' in router


def test_source_query_has_personal_compatibility_and_space_acl() -> None:
    router = (ROOT / "gateway/api_gateway/routers/knowledge.py").read_text()
    client = (ROOT / "frontend/src/api/client.ts").read_text()

    assert "space_id: str | None = None" in router
    assert "accessible_source_predicate(context)" in router
    assert "KnowledgeSource.owner_id == current_user.id" in router
    assert "options?.spaceId" in client
    assert "options?.status" in client


def test_governed_source_delete_decision_is_behavioral() -> None:
    assert not _source_requires_withdrawal(
        SimpleNamespace(space_id=None, active_version_id=None, status="draft")
    )
    assert _source_requires_withdrawal(
        SimpleNamespace(space_id="space-1", active_version_id=None, status="draft")
    )
    assert _source_requires_withdrawal(
        SimpleNamespace(space_id=None, active_version_id="version-1", status="published")
    )
    assert _source_requires_withdrawal(
        SimpleNamespace(space_id=None, active_version_id=None, status="review")
    )


def test_enterprise_search_feedback_and_quality_workbench_are_space_scoped() -> None:
    employee = (ROOT / "frontend/src/pages/EnterpriseKnowledgePage.tsx").read_text()
    governance = (ROOT / "frontend/src/pages/KnowledgeCenterPage.tsx").read_text()
    client = (ROOT / "frontend/src/api/client.ts").read_text()
    query = (ROOT / "knowledge/query.py").read_text()

    assert "apiSubmitKnowledgeFeedback" in employee
    assert "有帮助" in employee and "内容过期" in employee and "提交纠正" in employee
    assert "source_system" in employee and "review_due_at" in employee
    assert "selectedSpaceId, 12" in employee
    assert "space_id: spaceId || null" in client
    assert "KnowledgeSource.space_id == space_id" in query
    assert "质量与反馈" in governance
    assert "治理健康分" in governance
    assert "扫描到期复审" in governance
    assert "选择并合并" in governance
    assert "apiUploadDocument" not in governance
    assert "apiListKnowledgeSyncRuns" not in client
    assert "apiRetryKnowledgeSyncRun" not in client
