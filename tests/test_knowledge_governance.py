from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from gateway.api_gateway.main import app
from infra.storage.models import (
    KnowledgeFeedback,
    KnowledgeReviewTask,
    KnowledgeSource,
    KnowledgeSourceVersion,
)
from knowledge.access import KnowledgeAccessContext
from knowledge.governance import (
    FeedbackTarget,
    create_knowledge_feedback,
    resolve_knowledge_feedback,
)
from knowledge.lifecycle import reject_source_version, reopen_due_review_tasks


class ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeSession:
    def __init__(self):
        self.added = []
        self.flushed = 0

    def add(self, row):
        self.added.append(row)

    async def scalar(self, statement):
        return None

    async def flush(self):
        self.flushed += 1


@pytest.mark.asyncio
async def test_acl_authorized_viewer_can_submit_feedback_for_foreign_owned_source(monkeypatch):
    source = KnowledgeSource(
        id="source-1",
        owner_id="owner-user",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        space_id="space-1",
        title="员工制度",
        content_hash="hash",
        authority="official",
        classification="internal",
        status="published",
    )
    context = KnowledgeAccessContext(
        user_id="viewer-user",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        subjects=(("user", "viewer-user"),),
        clearance="internal",
        space_roles={"space-1": "viewer"},
    )

    async def fake_context(*args, **kwargs):
        return context

    async def fake_target(*args, **kwargs):
        assert kwargs["access_context"] is context
        return FeedbackTarget("knowledge_page", "page-1", source, "version-1", "员工制度")

    monkeypatch.setattr("knowledge.governance.resolve_access_context", fake_context)
    monkeypatch.setattr("knowledge.governance.resolve_feedback_target", fake_target)
    db = FakeSession()
    feedback = await create_knowledge_feedback(
        db,
        user=SimpleNamespace(id="viewer-user"),
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        target_type="knowledge_page",
        target_id="page-1",
        feedback_type="outdated",
    )

    assert feedback.user_id == "viewer-user"
    assert feedback.feedback_metadata["source_id"] == "source-1"
    assert feedback.feedback_metadata["space_id"] == "space-1"
    assert db.added == [feedback]
    assert db.flushed == 1


@pytest.mark.asyncio
async def test_helpful_feedback_is_auto_applied_and_deduplicated(monkeypatch):
    source = KnowledgeSource(
        id="source-1",
        owner_id="owner-user",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        space_id="space-1",
        title="员工制度",
        content_hash="hash",
        authority="official",
        classification="internal",
        status="published",
    )
    context = KnowledgeAccessContext(
        user_id="viewer-user",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        subjects=(("user", "viewer-user"),),
        clearance="internal",
        space_roles={"space-1": "viewer"},
    )
    existing = KnowledgeFeedback(
        id="feedback-1",
        user_id="viewer-user",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        target_type="knowledge_page",
        target_id="page-1",
        feedback_type="helpful",
        feedback_metadata={"deduplicated_submissions": 1},
        applied=True,
        created_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    async def fake_context(*args, **kwargs):
        return context

    async def fake_target(*args, **kwargs):
        return FeedbackTarget("knowledge_page", "page-1", source, "version-1", "员工制度")

    class DedupeSession(FakeSession):
        async def scalar(self, statement):
            return existing

    monkeypatch.setattr("knowledge.governance.resolve_access_context", fake_context)
    monkeypatch.setattr("knowledge.governance.resolve_feedback_target", fake_target)
    db = DedupeSession()
    result = await create_knowledge_feedback(
        db,
        user=SimpleNamespace(id="viewer-user"),
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        target_type="knowledge_page",
        target_id="page-1",
        feedback_type="helpful",
        score=1,
    )

    assert result is existing
    assert result.applied is True
    assert result.feedback_metadata["resolution"] == "signal_recorded"
    assert result.feedback_metadata["deduplicated_submissions"] == 2
    assert db.added == []


@pytest.mark.asyncio
async def test_feedback_rejects_target_outside_acl(monkeypatch):
    context = KnowledgeAccessContext(
        user_id="outsider",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        subjects=(("user", "outsider"),),
        clearance="internal",
        space_roles={},
    )

    async def fake_context(*args, **kwargs):
        return context

    async def fake_target(*args, **kwargs):
        return None

    monkeypatch.setattr("knowledge.governance.resolve_access_context", fake_context)
    monkeypatch.setattr("knowledge.governance.resolve_feedback_target", fake_target)
    with pytest.raises(LookupError, match="knowledge_feedback_target_not_found"):
        await create_knowledge_feedback(
            FakeSession(),
            user=SimpleNamespace(id="outsider"),
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            target_type="knowledge_source",
            target_id="source-1",
            feedback_type="helpful",
        )


@pytest.mark.asyncio
async def test_needs_revision_feedback_reopens_publisher_review(monkeypatch):
    source = KnowledgeSource(
        id="source-1",
        owner_id="owner-user",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        space_id="space-1",
        title="员工制度",
        content_hash="hash",
        authority="official",
        classification="internal",
        status="published",
        active_version_id="version-1",
        review_due_at=datetime.now(UTC) + timedelta(days=30),
    )
    feedback = KnowledgeFeedback(
        id="feedback-1",
        user_id="viewer-user",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        target_type="knowledge_page",
        target_id="page-1",
        feedback_type="incorrect",
        feedback_metadata={"source_id": "source-1"},
    )
    task = KnowledgeReviewTask(
        id="review-1",
        source_version_id="version-1",
        space_id="space-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        status="approved",
        required_role="publisher",
        decided_by="publisher-1",
        decided_at=datetime.now(UTC) - timedelta(days=5),
        diff_summary={"document_version": 1},
    )
    context = KnowledgeAccessContext(
        user_id="reviewer-user",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        subjects=(("user", "reviewer-user"),),
        clearance="internal",
        space_roles={"space-1": "reviewer"},
    )

    async def fake_context(*args, **kwargs):
        return context

    async def fake_target(*args, **kwargs):
        return FeedbackTarget("knowledge_page", "page-1", source, "version-1", "员工制度")

    class ResolutionSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.scalar_calls = 0

        async def scalar(self, statement):
            self.scalar_calls += 1
            return feedback if self.scalar_calls == 1 else task

    monkeypatch.setattr("knowledge.governance.resolve_access_context", fake_context)
    monkeypatch.setattr("knowledge.governance.resolve_feedback_target", fake_target)
    db = ResolutionSession()
    result = await resolve_knowledge_feedback(
        db,
        feedback_id="feedback-1",
        user=SimpleNamespace(id="reviewer-user"),
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        resolution="needs_revision",
        comment="需由制度负责人修订",
    )

    assert result.applied is True
    assert task.status == "pending"
    assert task.diff_summary["review_reason"] == "feedback_resolution"
    assert task.diff_summary["feedback_id"] == "feedback-1"
    assert task.diff_summary["review_history"][0]["status"] == "approved"
    assert source.source_metadata["needs_review"] is True
    assert source.review_due_at <= datetime.now(UTC)


@pytest.mark.asyncio
async def test_due_review_reuses_unique_task_and_preserves_history():
    due_at = datetime.now(UTC) - timedelta(days=1)
    source = KnowledgeSource(
        id="source-1",
        owner_id="owner-1",
        steward_id="steward-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        space_id="space-1",
        title="安全制度",
        content_hash="hash",
        authority="official",
        classification="internal",
        status="published",
        active_version_id="version-1",
        review_due_at=due_at,
    )
    task = KnowledgeReviewTask(
        id="review-1",
        source_version_id="version-1",
        space_id="space-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        status="approved",
        required_role="publisher",
        decided_by="publisher-1",
        decided_at=datetime.now(UTC) - timedelta(days=180),
        decision_comment="首次发布",
        diff_summary={"document_version": 1},
    )

    class DueSession(FakeSession):
        async def execute(self, statement):
            return ScalarRows([(source, task)])

    db = DueSession()
    result = await reopen_due_review_tasks(
        db,
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        space_ids=("space-1",),
    )

    assert result == {"scanned": 1, "reopened": 1, "already_pending": 0, "blocked": 0}
    assert task.status == "pending"
    assert task.decided_by is None and task.decided_at is None
    assert task.diff_summary["review_reason"] == "scheduled_recertification"
    assert task.diff_summary["review_history"][0]["status"] == "approved"
    assert source.source_metadata["needs_review"] is True
    assert db.added == []


@pytest.mark.asyncio
async def test_recertification_rejection_keeps_active_published_assets():
    source = KnowledgeSource(
        id="source-1",
        owner_id="owner-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        space_id="space-1",
        title="财务制度",
        content_hash="hash",
        authority="official",
        classification="internal",
        status="published",
        active_version_id="version-1",
        review_due_at=datetime.now(UTC) - timedelta(days=1),
    )
    version = KnowledgeSourceVersion(
        id="version-1",
        source_id="source-1",
        version_number=1,
        content_hash="hash",
        compiler_version="v1",
        status="published",
    )
    task = KnowledgeReviewTask(
        id="review-1",
        source_version_id="version-1",
        space_id="space-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        status="pending",
        required_role="publisher",
        diff_summary={"review_reason": "scheduled_recertification"},
    )

    class RejectSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.executed = 0

        async def get(self, model, key):
            if model is KnowledgeSourceVersion:
                return version
            if model is KnowledgeSource:
                return source
            return None

        async def scalar(self, statement):
            return task

        async def execute(self, statement):
            self.executed += 1
            raise AssertionError("周期复审驳回不应归档 active version 的派生资产")

    db = RejectSession()
    result = await reject_source_version(
        db,
        source_version_id="version-1",
        decided_by="publisher-2",
        comment="制度责任人需补充依据",
    )

    assert result["recertification"] is True
    assert source.status == "published"
    assert version.status == "published"
    assert source.source_metadata["needs_review"] is True
    assert source.source_metadata["recertification_rejected"] is True
    assert task.status == "rejected"
    assert db.executed == 0


def test_governance_openapi_exposes_feedback_health_and_due_review_actions():
    paths = app.openapi()["paths"]
    assert {"get", "post"}.issubset(paths["/api/v1/knowledge/feedback"])
    assert "post" in paths["/api/v1/knowledge/feedback/{feedback_id}/resolve"]
    assert "get" in paths["/api/v1/knowledge/governance/health"]
    assert "post" in paths["/api/v1/knowledge/reviews/reconcile-due"]


def test_query_governance_metadata_is_present_once_for_page_and_claim():
    source = open("knowledge/query.py", encoding="utf-8").read()
    page_block = source[
        source.index('"source_type": "knowledge_page"') : source.index(
            '"source_type": "knowledge_claim"'
        )
    ]
    claim_block = source[
        source.index('"source_type": "knowledge_claim"') : source.index(
            '"disclosure_stage": "relation"'
        )
    ]
    assert page_block.count("**_source_governance(source)") == 1
    assert "**_source_governance(source)" in claim_block
    assert "KnowledgeSource.space_id == space_id" in source
    assert source.count("source_space,") >= 4
