"""企业知识版本发布、驳回与撤回生命周期。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    KnowledgeClaim,
    KnowledgePage,
    KnowledgeRelation,
    KnowledgeReviewTask,
    KnowledgeSource,
    KnowledgeSourceVersion,
    KnowledgeSpace,
)
from knowledge.domain import KnowledgeStatus


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
    if source.effective_to is not None and source.effective_to <= datetime.now(UTC):
        raise ValueError("knowledge_source_expired")

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
    version.compiled_at = version.compiled_at or datetime.now(UTC)
    source.active_version_id = version.id
    source.status = KnowledgeStatus.PUBLISHED.value
    source.sync_status = "current"
    if source.space_id:
        space = await db.get(KnowledgeSpace, source.space_id)
        if space is not None:
            source.review_due_at = datetime.now(UTC) + timedelta(
                days=max(1, space.review_cycle_days)
            )

    task = await db.scalar(
        select(KnowledgeReviewTask).where(
            KnowledgeReviewTask.source_version_id == source_version_id
        )
    )
    if task is not None:
        task.status = "approved"
        task.decided_by = decided_by
        task.decided_at = datetime.now(UTC)
        task.decision_comment = comment
    await db.flush()
    return {
        "published": True,
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
    version.status = KnowledgeStatus.ARCHIVED.value
    for model in (KnowledgePage, KnowledgeClaim, KnowledgeRelation):
        await db.execute(
            update(model)
            .where(model.source_version_id == version.id)
            .values(status=KnowledgeStatus.ARCHIVED.value)
        )
    source.status = (
        KnowledgeStatus.PUBLISHED.value if source.active_version_id else KnowledgeStatus.DRAFT.value
    )
    task = await db.scalar(
        select(KnowledgeReviewTask).where(
            KnowledgeReviewTask.source_version_id == source_version_id
        )
    )
    if task is not None:
        task.status = "rejected"
        task.decided_by = decided_by
        task.decided_at = datetime.now(UTC)
        task.decision_comment = comment
    await db.flush()
    return {
        "rejected": True,
        "source_id": source.id,
        "source_version_id": version.id,
    }


async def withdraw_source(
    db: AsyncSession,
    *,
    source: KnowledgeSource,
    decided_by: str,
    reason: str,
) -> dict[str, str | bool]:
    source.status = KnowledgeStatus.DEPRECATED.value
    source.sync_status = "deleted"
    source.deleted_at = datetime.now(UTC)
    source.source_metadata = {
        **(source.source_metadata or {}),
        "withdrawn_by": decided_by,
        "withdraw_reason": reason,
        "withdrawn_at": source.deleted_at.isoformat(),
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
