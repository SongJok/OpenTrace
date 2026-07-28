"""企业数据保留、Legal Hold 与删除传播。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.config.settings import settings
from infra.storage.database import Base
from infra.storage.models import Attachment, DataDeletionJob, LegalHold
from infra.storage.object_store import get_object_store

_GOVERNANCE_TABLES = {"data_deletion_jobs", "legal_holds", "audit_logs", "revoked_tokens"}


async def active_legal_holds(
    db: AsyncSession, *, tenant_id: str, workspace_id: str | None = None
) -> list[LegalHold]:
    now = datetime.now(UTC)
    query = select(LegalHold).where(
        LegalHold.tenant_id == tenant_id,
        LegalHold.status == "active",
        (LegalHold.expires_at.is_(None) | (LegalHold.expires_at > now)),
    )
    if workspace_id:
        query = query.where(LegalHold.workspace_id.in_([workspace_id, "*"]))
    return list((await db.scalars(query)).all())


async def create_legal_hold(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    resource_type: str,
    resource_id: str | None,
    reason: str,
    created_by: str,
    expires_at: datetime | None = None,
) -> LegalHold:
    hold = LegalHold(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=resource_id,
        reason=reason,
        created_by=created_by,
        expires_at=expires_at,
    )
    db.add(hold)
    await db.flush()
    return hold


async def request_tenant_deletion(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str | None,
    requested_by: str,
    reason: str,
) -> DataDeletionJob:
    holds = await active_legal_holds(db, tenant_id=tenant_id, workspace_id=workspace_id)
    status = "blocked" if holds else "pending"
    job = DataDeletionJob(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        requested_by=requested_by,
        reason=reason,
        status=status,
        phase="legal_hold" if holds else "grace_period",
        progress={"blocking_hold_ids": [hold.id for hold in holds]},
        execute_after=datetime.now(UTC)
        + timedelta(days=max(0, int(settings.enterprise_deletion_grace_days))),
    )
    db.add(job)
    await db.flush()
    return job


def deletion_table_order() -> list[Any]:
    """按外键反向拓扑删除所有直接带 tenant_id 的业务表。"""
    return [
        table
        for table in reversed(Base.metadata.sorted_tables)
        if "tenant_id" in table.c and table.name not in _GOVERNANCE_TABLES
    ]


async def execute_deletion_job(db: AsyncSession, job: DataDeletionJob) -> dict[str, int]:
    now = datetime.now(UTC)
    if job.status == "completed":
        return {
            str(key): int(value)
            for key, value in dict(job.progress or {}).items()
            if isinstance(value, int)
        }
    if job.execute_after > now:
        raise ValueError("删除任务仍在冷静期")
    holds = await active_legal_holds(db, tenant_id=job.tenant_id, workspace_id=job.workspace_id)
    if holds:
        job.status = "blocked"
        job.phase = "legal_hold"
        job.progress = {"blocking_hold_ids": [hold.id for hold in holds]}
        await db.flush()
        raise ValueError("删除被 Legal Hold 阻止")

    attachment_query = select(Attachment.object_key).where(
        Attachment.tenant_id == job.tenant_id,
        Attachment.object_key.is_not(None),
    )
    if job.workspace_id:
        attachment_query = attachment_query.where(Attachment.workspace_id == job.workspace_id)
    object_keys = set((await db.scalars(attachment_query)).all())
    object_store = get_object_store()
    if object_store:
        for key in object_keys:
            if key:
                await object_store.delete(str(key))

    job.status = "running"
    job.phase = "database"
    deleted: dict[str, int] = {}
    for table in deletion_table_order():
        statement = delete(table).where(table.c.tenant_id == job.tenant_id)
        if job.workspace_id and "workspace_id" in table.c:
            statement = statement.where(table.c.workspace_id == job.workspace_id)
        result = await db.execute(statement)
        deleted[table.name] = int(result.rowcount or 0)
    job.status = "completed"
    job.phase = "done"
    job.progress = deleted
    job.completed_at = now
    await db.flush()
    return deleted


async def deletion_job_loop() -> None:
    """处理到期删除任务；Legal Hold 与对象存储错误均 fail-closed。"""
    import asyncio

    from infra.storage.database import AsyncSessionLocal
    from tenant.tenant_rls import set_worker_session

    while True:
        async with AsyncSessionLocal() as db:
            await set_worker_session(db)
            job = await db.scalar(
                select(DataDeletionJob)
                .where(
                    DataDeletionJob.status == "pending",
                    DataDeletionJob.execute_after <= datetime.now(UTC),
                )
                .order_by(DataDeletionJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                await db.rollback()
            else:
                try:
                    await execute_deletion_job(db, job)
                    await db.commit()
                except ValueError:
                    await db.commit()
                except Exception as exc:  # noqa: BLE001
                    job.status = "failed"
                    job.phase = "failed"
                    job.error = str(exc)[:2000]
                    await db.commit()
        await asyncio.sleep(max(1, int(settings.data_deletion_poll_seconds)))
