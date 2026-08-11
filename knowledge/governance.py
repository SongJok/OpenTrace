"""企业知识反馈、治理范围与健康度聚合服务。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    KnowledgeClaim,
    KnowledgeCompilationJob,
    KnowledgeFeedback,
    KnowledgeLintIssue,
    KnowledgeMergeCase,
    KnowledgePage,
    KnowledgeReviewTask,
    KnowledgeSource,
    KnowledgeSourceVersion,
    User,
)
from knowledge.access import (
    KnowledgeAccessContext,
    accessible_source_predicate,
    classification_allows,
    resolve_access_context,
    role_allows,
)
from knowledge.lint import merge_case_ids_in_claim_scope

ALLOWED_FEEDBACK_TYPES = {
    "helpful",
    "unhelpful",
    "incorrect",
    "outdated",
    "correction",
    "like",
    "dislike",
}
ALLOWED_RESOLUTIONS = {"acknowledged", "needs_revision", "corrected", "dismissed"}
ACTIONABLE_FEEDBACK_TYPES = {"unhelpful", "incorrect", "outdated", "correction", "dislike"}
AUTO_APPLIED_FEEDBACK_TYPES = {"helpful", "like"}


@dataclass(frozen=True, slots=True)
class FeedbackTarget:
    target_type: str
    target_id: str
    source: KnowledgeSource
    source_version_id: str | None
    title: str


def _source_snapshot(target: FeedbackTarget) -> dict[str, Any]:
    source = target.source
    return {
        "source": "knowledge_api",
        "source_id": source.id,
        "source_title": source.title,
        "source_owner_id": source.owner_id,
        "space_id": source.space_id,
        "source_version_id": target.source_version_id or source.active_version_id,
        "classification": source.classification,
        "authority": source.authority,
        "target_title": target.title,
    }


async def resolve_feedback_target(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: str,
    tenant_id: str,
    workspace_id: str,
    access_context: KnowledgeAccessContext | None = None,
    require_published: bool = True,
) -> FeedbackTarget | None:
    """将 Page/Claim/Source 统一归因到稳定 KnowledgeSource。"""

    source_access = (
        accessible_source_predicate(access_context) if access_context is not None else True
    )
    common_source_scope = (
        KnowledgeSource.tenant_id == tenant_id,
        KnowledgeSource.workspace_id == workspace_id,
        source_access,
    )
    if target_type == "knowledge_source":
        source_conditions = [KnowledgeSource.id == target_id, *common_source_scope]
        if require_published:
            source_conditions.append(KnowledgeSource.status == "published")
        row = await db.scalar(select(KnowledgeSource).where(*source_conditions))
        if row is None:
            return None
        return FeedbackTarget(target_type, target_id, row, row.active_version_id, row.title)

    if target_type == "knowledge_page":
        row = (
            await db.execute(
                select(KnowledgePage, KnowledgeSourceVersion, KnowledgeSource)
                .join(
                    KnowledgeSourceVersion,
                    KnowledgePage.source_version_id == KnowledgeSourceVersion.id,
                )
                .join(KnowledgeSource, KnowledgeSourceVersion.source_id == KnowledgeSource.id)
                .where(
                    KnowledgePage.id == target_id,
                    KnowledgePage.tenant_id == tenant_id,
                    KnowledgePage.workspace_id == workspace_id,
                    *common_source_scope,
                    *(
                        (
                            KnowledgePage.status == "published",
                            KnowledgeSource.status == "published",
                            KnowledgeSource.active_version_id == KnowledgeSourceVersion.id,
                        )
                        if require_published
                        else ()
                    ),
                )
            )
        ).first()
        if row is None:
            return None
        page, version, source = row
        return FeedbackTarget(target_type, target_id, source, version.id, page.title)

    if target_type == "knowledge_claim":
        row = (
            await db.execute(
                select(KnowledgeClaim, KnowledgePage, KnowledgeSourceVersion, KnowledgeSource)
                .join(KnowledgePage, KnowledgeClaim.page_id == KnowledgePage.id)
                .join(
                    KnowledgeSourceVersion,
                    KnowledgeClaim.source_version_id == KnowledgeSourceVersion.id,
                )
                .join(KnowledgeSource, KnowledgeSourceVersion.source_id == KnowledgeSource.id)
                .where(
                    KnowledgeClaim.id == target_id,
                    KnowledgeClaim.tenant_id == tenant_id,
                    KnowledgeClaim.workspace_id == workspace_id,
                    *common_source_scope,
                    *(
                        (
                            KnowledgeClaim.status == "published",
                            KnowledgeSource.status == "published",
                            KnowledgeSource.active_version_id == KnowledgeSourceVersion.id,
                        )
                        if require_published
                        else ()
                    ),
                )
            )
        ).first()
        if row is None:
            return None
        claim, page, version, source = row
        return FeedbackTarget(target_type, target_id, source, version.id, page.title)
    return None


async def create_knowledge_feedback(
    db: AsyncSession,
    *,
    user: User,
    tenant_id: str,
    workspace_id: str,
    target_type: str,
    target_id: str,
    feedback_type: str,
    score: float | None = None,
    correction: str | None = None,
    session_id: str | None = None,
) -> KnowledgeFeedback:
    normalized_type = feedback_type.strip().lower()
    if normalized_type not in ALLOWED_FEEDBACK_TYPES:
        raise ValueError("unsupported_knowledge_feedback_type")
    if normalized_type == "correction" and not (correction or "").strip():
        raise ValueError("knowledge_feedback_correction_required")

    context = await resolve_access_context(
        db,
        user=user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    target = await resolve_feedback_target(
        db,
        target_type=target_type,
        target_id=target_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        access_context=context,
    )
    if target is None:
        raise LookupError("knowledge_feedback_target_not_found")

    now = datetime.now(UTC)
    auto_applied = normalized_type in AUTO_APPLIED_FEEDBACK_TYPES
    dedupe_conditions = [
        KnowledgeFeedback.user_id == user.id,
        KnowledgeFeedback.tenant_id == tenant_id,
        KnowledgeFeedback.workspace_id == workspace_id,
        KnowledgeFeedback.target_type == target_type,
        KnowledgeFeedback.target_id == target_id,
        KnowledgeFeedback.feedback_type == normalized_type,
        KnowledgeFeedback.created_at >= now - timedelta(hours=24),
    ]
    if not auto_applied:
        dedupe_conditions.append(KnowledgeFeedback.applied.is_(False))
    existing = await db.scalar(
        select(KnowledgeFeedback)
        .where(*dedupe_conditions)
        .order_by(KnowledgeFeedback.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        metadata = dict(existing.feedback_metadata or {})
        existing.session_id = session_id or existing.session_id
        existing.score = score
        existing.correction = (correction or "").strip() or existing.correction
        existing.applied = auto_applied
        existing.created_at = now
        existing.feedback_metadata = {
            **_source_snapshot(target),
            **metadata,
            "deduplicated_submissions": int(metadata.get("deduplicated_submissions", 1)) + 1,
            "last_submitted_at": now.isoformat(),
            **(
                {"resolution": "signal_recorded", "resolved_at": now.isoformat()}
                if auto_applied
                else {}
            ),
        }
        await db.flush()
        return existing

    metadata = _source_snapshot(target)
    if auto_applied:
        metadata.update({"resolution": "signal_recorded", "resolved_at": now.isoformat()})
    feedback = KnowledgeFeedback(
        id=str(uuid.uuid4()),
        session_id=session_id,
        user_id=user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        target_type=target_type,
        target_id=target_id,
        feedback_type=normalized_type,
        score=score,
        correction=(correction or "").strip() or None,
        feedback_metadata=metadata,
        applied=auto_applied,
        created_at=now,
    )
    db.add(feedback)
    await db.flush()
    return feedback


def governable_space_ids(context: KnowledgeAccessContext) -> tuple[str, ...]:
    return tuple(
        space_id for space_id, role in context.space_roles.items() if role_allows(role, "reviewer")
    )


def _can_govern_source(
    *,
    source: KnowledgeSource,
    user: User,
    context: KnowledgeAccessContext,
    space_id: str | None,
) -> bool:
    if space_id and source.space_id != space_id:
        return False
    if not classification_allows(context.clearance, source.classification):
        return False
    if source.space_id:
        return role_allows(context.space_roles.get(source.space_id), "reviewer")
    return source.owner_id == user.id


async def list_knowledge_feedback(
    db: AsyncSession,
    *,
    user: User,
    tenant_id: str,
    workspace_id: str,
    space_id: str | None = None,
    applied: bool | None = False,
    actionable_only: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """返回当前用户有权治理的反馈；旧反馈也通过目标反查来源。"""

    context = await resolve_access_context(
        db,
        user=user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if space_id and not role_allows(context.space_roles.get(space_id), "reviewer"):
        raise PermissionError("knowledge_space_requires_reviewer")

    stmt = select(KnowledgeFeedback).where(
        KnowledgeFeedback.tenant_id == tenant_id,
        KnowledgeFeedback.workspace_id == workspace_id,
    )
    if applied is not None:
        stmt = stmt.where(KnowledgeFeedback.applied.is_(applied))
    if actionable_only:
        stmt = stmt.where(KnowledgeFeedback.feedback_type.in_(ACTIONABLE_FEEDBACK_TYPES))
    rows = list(
        (
            await db.execute(
                stmt.order_by(KnowledgeFeedback.created_at.desc()).limit(
                    max(1, min(limit, 200)) * 4
                )
            )
        ).scalars()
    )

    items: list[dict[str, Any]] = []
    for feedback in rows:
        target = await resolve_feedback_target(
            db,
            target_type=feedback.target_type,
            target_id=feedback.target_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            require_published=False,
        )
        if target is None or not _can_govern_source(
            source=target.source,
            user=user,
            context=context,
            space_id=space_id,
        ):
            continue
        metadata = {**_source_snapshot(target), **(feedback.feedback_metadata or {})}
        items.append(
            {
                "id": feedback.id,
                "target_type": feedback.target_type,
                "target_id": feedback.target_id,
                "feedback_type": feedback.feedback_type,
                "score": feedback.score,
                "correction": feedback.correction,
                "applied": feedback.applied,
                "user_id": feedback.user_id,
                "source_id": target.source.id,
                "source_title": target.source.title,
                "space_id": target.source.space_id,
                "source_version_id": target.source_version_id,
                "metadata": metadata,
                "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
            }
        )
        if len(items) >= max(1, min(limit, 200)):
            break
    return items


async def resolve_knowledge_feedback(
    db: AsyncSession,
    *,
    feedback_id: str,
    user: User,
    tenant_id: str,
    workspace_id: str,
    resolution: str,
    comment: str | None = None,
) -> KnowledgeFeedback:
    normalized_resolution = resolution.strip().lower()
    if normalized_resolution not in ALLOWED_RESOLUTIONS:
        raise ValueError("unsupported_knowledge_feedback_resolution")
    feedback = await db.scalar(
        select(KnowledgeFeedback).where(
            KnowledgeFeedback.id == feedback_id,
            KnowledgeFeedback.tenant_id == tenant_id,
            KnowledgeFeedback.workspace_id == workspace_id,
        )
    )
    if feedback is None:
        raise LookupError("knowledge_feedback_not_found")
    if feedback.applied:
        raise ValueError("knowledge_feedback_already_resolved")

    context = await resolve_access_context(
        db,
        user=user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    target = await resolve_feedback_target(
        db,
        target_type=feedback.target_type,
        target_id=feedback.target_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        require_published=False,
    )
    if target is None:
        raise LookupError("knowledge_feedback_target_not_found")
    if not _can_govern_source(source=target.source, user=user, context=context, space_id=None):
        raise PermissionError("knowledge_feedback_requires_reviewer")

    now = datetime.now(UTC)
    feedback.applied = True
    feedback.feedback_metadata = {
        **_source_snapshot(target),
        **(feedback.feedback_metadata or {}),
        "resolved_by": user.id,
        "resolved_at": now.isoformat(),
        "resolution": normalized_resolution,
        "resolution_comment": (comment or "").strip() or None,
    }
    if normalized_resolution in {"needs_revision", "corrected"}:
        target.source.source_metadata = {
            **(target.source.source_metadata or {}),
            "needs_review": True,
            "feedback_review_requested_at": now.isoformat(),
            "feedback_review_requested_by": user.id,
        }
        target.source.review_due_at = now
        if target.source.active_version_id:
            review_task = await db.scalar(
                select(KnowledgeReviewTask).where(
                    KnowledgeReviewTask.source_version_id == target.source.active_version_id
                )
            )
            if review_task is None:
                db.add(
                    KnowledgeReviewTask(
                        id=str(uuid.uuid4()),
                        source_version_id=target.source.active_version_id,
                        space_id=target.source.space_id,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        status="pending",
                        required_role="publisher",
                        requested_by=target.source.steward_id or target.source.owner_id,
                        diff_summary={
                            "review_reason": "feedback_resolution",
                            "feedback_id": feedback.id,
                            "feedback_type": feedback.feedback_type,
                            "review_history": [],
                        },
                        created_at=now,
                    )
                )
            else:
                summary = dict(review_task.diff_summary or {})
                history = list(summary.get("review_history") or [])
                if review_task.status != "pending" or review_task.decided_at:
                    history.append(
                        {
                            "status": review_task.status,
                            "decided_by": review_task.decided_by,
                            "decided_at": (
                                review_task.decided_at.isoformat()
                                if review_task.decided_at
                                else None
                            ),
                            "decision_comment": review_task.decision_comment,
                        }
                    )
                review_task.status = "pending"
                review_task.required_role = "publisher"
                review_task.assigned_to = None
                review_task.decided_by = None
                review_task.decided_at = None
                review_task.decision_comment = None
                review_task.created_at = now
                review_task.diff_summary = {
                    **summary,
                    "review_reason": "feedback_resolution",
                    "feedback_id": feedback.id,
                    "feedback_type": feedback.feedback_type,
                    "review_history": history[-20:],
                }
    await db.flush()
    return feedback


async def knowledge_governance_health(
    db: AsyncSession,
    *,
    user: User,
    tenant_id: str,
    workspace_id: str,
    space_id: str | None = None,
) -> dict[str, Any]:
    """聚合治理控制面指标，所有指标限定在 Reviewer 可治理的空间。"""

    context = await resolve_access_context(
        db,
        user=user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    allowed_spaces = governable_space_ids(context)
    if space_id:
        if space_id not in allowed_spaces:
            raise PermissionError("knowledge_space_requires_reviewer")
        allowed_spaces = (space_id,)
    if not allowed_spaces:
        return {
            "score": 100,
            "status": "healthy",
            "scope": {"space_id": space_id, "space_count": 0},
            "metrics": {},
        }

    sources = list(
        (
            await db.execute(
                select(KnowledgeSource).where(
                    KnowledgeSource.tenant_id == tenant_id,
                    KnowledgeSource.workspace_id == workspace_id,
                    KnowledgeSource.space_id.in_(allowed_spaces),
                    KnowledgeSource.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    sources = [
        source
        for source in sources
        if classification_allows(context.clearance, source.classification)
    ]
    source_ids = {source.id for source in sources}
    version_ids = {
        source.active_version_id for source in sources if source.active_version_id is not None
    }
    now = datetime.now(UTC)

    reviews = []
    jobs = []
    pages = []
    claims = []
    if source_ids:
        reviews = list(
            (
                await db.execute(
                    select(KnowledgeReviewTask)
                    .join(
                        KnowledgeSourceVersion,
                        KnowledgeReviewTask.source_version_id == KnowledgeSourceVersion.id,
                    )
                    .where(
                        KnowledgeSourceVersion.source_id.in_(source_ids),
                        KnowledgeReviewTask.tenant_id == tenant_id,
                        KnowledgeReviewTask.workspace_id == workspace_id,
                    )
                )
            ).scalars()
        )
        jobs = list(
            (
                await db.execute(
                    select(KnowledgeCompilationJob).where(
                        KnowledgeCompilationJob.source_id.in_(source_ids),
                        KnowledgeCompilationJob.tenant_id == tenant_id,
                        KnowledgeCompilationJob.workspace_id == workspace_id,
                    )
                )
            ).scalars()
        )
    if version_ids:
        pages = list(
            (
                await db.execute(
                    select(KnowledgePage).where(KnowledgePage.source_version_id.in_(version_ids))
                )
            ).scalars()
        )
        claims = list(
            (
                await db.execute(
                    select(KnowledgeClaim).where(KnowledgeClaim.source_version_id.in_(version_ids))
                )
            ).scalars()
        )

    claim_ids = {claim.id for claim in claims}
    merge_cases = list(
        (
            await db.execute(
                select(KnowledgeMergeCase).where(
                    KnowledgeMergeCase.tenant_id == tenant_id,
                    KnowledgeMergeCase.workspace_id == workspace_id,
                    KnowledgeMergeCase.status == "open",
                )
            )
        ).scalars()
    )
    scoped_merge_case_ids = merge_case_ids_in_claim_scope(merge_cases, claim_ids)
    resource_ids = source_ids | {row.id for row in pages} | claim_ids | scoped_merge_case_ids
    lint_issues = []
    if resource_ids:
        lint_issues = list(
            (
                await db.execute(
                    select(KnowledgeLintIssue).where(
                        KnowledgeLintIssue.tenant_id == tenant_id,
                        KnowledgeLintIssue.workspace_id == workspace_id,
                        KnowledgeLintIssue.status == "open",
                        KnowledgeLintIssue.resource_id.in_(resource_ids),
                    )
                )
            ).scalars()
        )

    feedback_items = await list_knowledge_feedback(
        db,
        user=user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        space_id=space_id,
        applied=False,
        actionable_only=True,
        limit=200,
    )
    metrics = {
        "sources": len(sources),
        "published_sources": sum(source.status == "published" for source in sources),
        "due_reviews": sum(
            source.status == "published"
            and source.review_due_at is not None
            and source.review_due_at <= now
            for source in sources
        ),
        "expired_sources": sum(
            source.effective_to is not None and source.effective_to <= now for source in sources
        ),
        "pending_reviews": sum(review.status == "pending" for review in reviews),
        "blocked_reviews": sum(
            (source.source_metadata or {}).get("recertification_rejected") is True
            for source in sources
        ),
        "failed_jobs": sum(job.status == "failed" for job in jobs),
        "stale_sources": sum(
            source.sync_status in {"stale", "error", "failed"} for source in sources
        ),
        "open_lint_issues": len(lint_issues),
        "open_lint_errors": sum(issue.severity == "error" for issue in lint_issues),
        "unresolved_feedback": len(feedback_items),
        "open_merge_cases": len(scoped_merge_case_ids),
    }
    penalty = (
        metrics["due_reviews"] * 5
        + metrics["expired_sources"] * 12
        + metrics["pending_reviews"] * 2
        + metrics["blocked_reviews"] * 8
        + metrics["failed_jobs"] * 6
        + metrics["stale_sources"] * 4
        + metrics["open_lint_issues"] * 2
        + metrics["open_lint_errors"] * 6
        + metrics["unresolved_feedback"] * 4
        + metrics["open_merge_cases"] * 6
    )
    score = max(0, 100 - min(100, penalty))
    status = "healthy" if score >= 85 else "attention" if score >= 60 else "critical"
    return {
        "score": score,
        "status": status,
        "scope": {"space_id": space_id, "space_count": len(allowed_spaces)},
        "metrics": metrics,
    }
