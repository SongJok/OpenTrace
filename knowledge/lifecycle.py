"""企业知识版本发布、驳回、周期复审与撤回生命周期。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    KnowledgeClaim,
    KnowledgeCompilationJob,
    KnowledgePage,
    KnowledgeRelation,
    KnowledgeReviewTask,
    KnowledgeSource,
    KnowledgeSourceVersion,
    KnowledgeSpace,
)
from knowledge.domain import KnowledgeStatus


def _is_scheduled_recertification(task: KnowledgeReviewTask | None) -> bool:
    return bool(
        task and (task.diff_summary or {}).get("review_reason") == "scheduled_recertification"
    )


def _review_history_entry(task: KnowledgeReviewTask) -> dict[str, str | None]:
    return {
        "status": task.status,
        "decided_by": task.decided_by,
        "decided_at": task.decided_at.isoformat() if task.decided_at else None,
        "decision_comment": task.decision_comment,
    }


async def publish_source_version(
    db: AsyncSession,
    *,
    source_version_id: str,
    decided_by: str,
    comment: str | None = None,
) -> dict[str, str | bool]:
    version = await db.get(KnowledgeSourceVersion, source_version_id)
    if version is None:
        raise ValueError("knowledge_source_version_not_found")
    source = await db.get(KnowledgeSource, version.source_id)
    if source is None or source.deleted_at is not None:
        raise ValueError("knowledge_source_not_publishable")
    now = datetime.now(UTC)
    if source.effective_to is not None and source.effective_to <= now:
        raise ValueError("knowledge_source_expired")

    task = await db.scalar(
        select(KnowledgeReviewTask).where(
            KnowledgeReviewTask.source_version_id == source_version_id
        )
    )
    recertification = _is_scheduled_recertification(task)
    previous_version_id = source.active_version_id
    if previous_version_id and previous_version_id != version.id:
        previous = await db.get(KnowledgeSourceVersion, previous_version_id)
        if previous is not None:
            previous.status = KnowledgeStatus.ARCHIVED.value
            for model in (KnowledgePage, KnowledgeClaim, KnowledgeRelation):
                await db.execute(
                    update(model)
                    .where(model.source_version_id == previous.id)
                    .values(status=KnowledgeStatus.ARCHIVED.value)
                )

    for model in (KnowledgePage, KnowledgeClaim, KnowledgeRelation):
        await db.execute(
            update(model)
            .where(model.source_version_id == version.id)
            .values(status=KnowledgeStatus.PUBLISHED.value)
        )
    version.status = KnowledgeStatus.PUBLISHED.value
    version.compiled_at = version.compiled_at or now
    source.active_version_id = version.id
    source.status = KnowledgeStatus.PUBLISHED.value
    source.sync_status = "current"
    if source.space_id:
        space = await db.get(KnowledgeSpace, source.space_id)
        if space is not None:
            source.review_due_at = now + timedelta(days=max(1, space.review_cycle_days))

    metadata = dict(source.source_metadata or {})
    metadata.pop("recertification_rejected", None)
    metadata.pop("recertification_rejected_at", None)
    metadata.pop("recertification_rejected_by", None)
    metadata.update(
        {
            "last_reviewed_at": now.isoformat(),
            "last_reviewed_by": decided_by,
            "needs_review": False,
        }
    )
    source.source_metadata = metadata

    if task is not None:
        task.status = "approved"
        task.decided_by = decided_by
        task.decided_at = now
        task.decision_comment = comment
    await db.flush()
    return {
        "published": True,
        "recertification": recertification,
        "source_id": source.id,
        "source_version_id": version.id,
    }


async def reject_source_version(
    db: AsyncSession,
    *,
    source_version_id: str,
    decided_by: str,
    comment: str,
) -> dict[str, str | bool]:
    version = await db.get(KnowledgeSourceVersion, source_version_id)
    if version is None:
        raise ValueError("knowledge_source_version_not_found")
    source = await db.get(KnowledgeSource, version.source_id)
    if source is None:
        raise ValueError("knowledge_source_not_found")
    task = await db.scalar(
        select(KnowledgeReviewTask).where(
            KnowledgeReviewTask.source_version_id == source_version_id
        )
    )
    recertification = _is_scheduled_recertification(task) and source.active_version_id == version.id
    now = datetime.now(UTC)

    if recertification:
        # 周期复审驳回表示知识需要修订，不得破坏仍被 active_version_id 引用的已发布资产。
        version.status = KnowledgeStatus.PUBLISHED.value
        source.status = KnowledgeStatus.PUBLISHED.value
        source.source_metadata = {
            **(source.source_metadata or {}),
            "needs_review": True,
            "recertification_rejected": True,
            "recertification_rejected_at": now.isoformat(),
            "recertification_rejected_by": decided_by,
        }
    else:
        version.status = KnowledgeStatus.ARCHIVED.value
        for model in (KnowledgePage, KnowledgeClaim, KnowledgeRelation):
            await db.execute(
                update(model)
                .where(model.source_version_id == version.id)
                .values(status=KnowledgeStatus.ARCHIVED.value)
            )
        source.status = (
            KnowledgeStatus.PUBLISHED.value
            if source.active_version_id
            else KnowledgeStatus.DRAFT.value
        )

    if task is not None:
        task.status = "rejected"
        task.decided_by = decided_by
        task.decided_at = now
        task.decision_comment = comment
    await db.flush()
    return {
        "rejected": True,
        "recertification": recertification,
        "source_id": source.id,
        "source_version_id": version.id,
    }


async def reopen_due_review_tasks(
    db: AsyncSession,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    space_ids: tuple[str, ...] | None = None,
    limit: int = 200,
) -> dict[str, int]:
    """将已到期的已发布版本重新放回唯一审核任务，不中断员工读取。"""

    now = datetime.now(UTC)
    stmt = (
        select(KnowledgeSource, KnowledgeReviewTask)
        .outerjoin(
            KnowledgeReviewTask,
            KnowledgeReviewTask.source_version_id == KnowledgeSource.active_version_id,
        )
        .where(
            KnowledgeSource.status == KnowledgeStatus.PUBLISHED.value,
            KnowledgeSource.active_version_id.is_not(None),
            KnowledgeSource.review_due_at.is_not(None),
            KnowledgeSource.review_due_at <= now,
            or_(KnowledgeSource.effective_to.is_(None), KnowledgeSource.effective_to > now),
            KnowledgeSource.deleted_at.is_(None),
        )
        .order_by(KnowledgeSource.review_due_at.asc())
        .with_for_update(of=KnowledgeSource, skip_locked=True)
        .limit(max(1, min(limit, 1000)))
    )
    if tenant_id:
        stmt = stmt.where(KnowledgeSource.tenant_id == tenant_id)
    if workspace_id:
        stmt = stmt.where(KnowledgeSource.workspace_id == workspace_id)
    if space_ids is not None:
        if not space_ids:
            return {"scanned": 0, "reopened": 0, "already_pending": 0, "blocked": 0}
        stmt = stmt.where(KnowledgeSource.space_id.in_(space_ids))

    rows = (await db.execute(stmt)).all()
    reopened = 0
    already_pending = 0
    blocked = 0
    for source, task in rows:
        metadata = dict(source.source_metadata or {})
        if metadata.get("recertification_rejected") is True:
            blocked += 1
            continue
        metadata.update(
            {
                "needs_review": True,
                "review_reopened_at": now.isoformat(),
            }
        )
        source.source_metadata = metadata
        due_at = source.review_due_at.isoformat() if source.review_due_at else None
        if task is None:
            db.add(
                KnowledgeReviewTask(
                    id=str(uuid.uuid4()),
                    source_version_id=source.active_version_id,
                    space_id=source.space_id,
                    tenant_id=source.tenant_id,
                    workspace_id=source.workspace_id,
                    status="pending",
                    required_role="publisher",
                    requested_by=source.steward_id or source.owner_id,
                    diff_summary={
                        "review_reason": "scheduled_recertification",
                        "review_due_at": due_at,
                        "review_history": [],
                    },
                    created_at=now,
                )
            )
            reopened += 1
            continue

        summary = dict(task.diff_summary or {})
        if task.status == "pending" and summary.get("review_reason") == "scheduled_recertification":
            already_pending += 1
            continue
        history = list(summary.get("review_history") or [])
        if task.status != "pending" or task.decided_at or task.decided_by:
            history.append(_review_history_entry(task))
        task.status = "pending"
        task.required_role = "publisher"
        task.assigned_to = None
        task.decided_by = None
        task.decided_at = None
        task.decision_comment = None
        task.created_at = now
        task.diff_summary = {
            **summary,
            "review_reason": "scheduled_recertification",
            "review_due_at": due_at,
            "review_history": history[-20:],
        }
        reopened += 1
    await db.flush()
    return {
        "scanned": len(rows),
        "reopened": reopened,
        "already_pending": already_pending,
        "blocked": blocked,
    }


async def withdraw_source(
    db: AsyncSession,
    *,
    source: KnowledgeSource,
    decided_by: str,
    reason: str,
) -> dict[str, str | bool]:
    # 与编译器对同一来源串行化，避免撤回后被在途或补偿任务重新发布。
    await db.refresh(source, with_for_update=True)
    now = datetime.now(UTC)
    source.status = KnowledgeStatus.DEPRECATED.value
    source.sync_status = "deleted"
    source.deleted_at = now
    source.source_metadata = {
        **(source.source_metadata or {}),
        "withdrawn_by": decided_by,
        "withdraw_reason": reason,
        "withdrawn_at": source.deleted_at.isoformat(),
    }
    active_jobs = list(
        (
            await db.execute(
                select(KnowledgeCompilationJob)
                .where(
                    KnowledgeCompilationJob.source_id == source.id,
                    KnowledgeCompilationJob.status.in_(["pending", "running"]),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for job in active_jobs:
        job.status = "succeeded"
        job.completed_at = now
        job.error = None
        job.result_metadata = {
            **(job.result_metadata or {}),
            "reason": "source_withdrawn",
        }

    if source.active_version_id:
        version = await db.get(KnowledgeSourceVersion, source.active_version_id)
        if version is not None:
            version.status = KnowledgeStatus.ARCHIVED.value
        for model in (KnowledgePage, KnowledgeClaim, KnowledgeRelation):
            await db.execute(
                update(model)
                .where(model.source_version_id == source.active_version_id)
                .values(status=KnowledgeStatus.ARCHIVED.value)
            )
    await db.flush()
    return {"withdrawn": True, "source_id": source.id}
