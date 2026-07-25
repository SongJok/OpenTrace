"""企业知识连接器 Snapshot 的持久化 Worker 执行面。"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.orm import aliased

from infra.config.settings import settings
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import (
    Document,
    KnowledgeConnector,
    KnowledgeSource,
    KnowledgeSourcePermission,
    KnowledgeSpace,
    KnowledgeSyncItem,
    KnowledgeSyncRun,
)
from knowledge.compiler import stable_id
from knowledge.domain import KnowledgeAuthority, KnowledgeStatus, source_status_during_refresh
from knowledge.jobs import enqueue_document_compile
from knowledge.lifecycle import withdraw_source
from services.document_ingestion import ingest_document


def _metadata(
    item: KnowledgeSyncItem, connector: KnowledgeConnector, space: KnowledgeSpace
) -> dict:
    return {
        **(item.source_metadata or {}),
        "knowledge_space_id": connector.space_id,
        "knowledge_steward_id": connector.owner_id,
        "classification": item.classification or space.default_classification,
        "knowledge_authority": item.authority,
        "source_system": connector.connector_type,
        "publish_policy": space.publish_policy,
        "external_ref": f"{connector.id}:{item.external_id}",
    }


async def _refresh_run(run_id: str) -> None:
    async with AsyncSessionLocal() as db:
        run = await db.get(KnowledgeSyncRun, run_id)
        if run is None:
            return
        connector = await db.get(KnowledgeConnector, run.connector_id)
        counts = dict(
            (
                await db.execute(
                    select(KnowledgeSyncItem.status, func.count(KnowledgeSyncItem.id))
                    .where(KnowledgeSyncItem.run_id == run_id)
                    .group_by(KnowledgeSyncItem.status)
                )
            ).all()
        )
        stats = {
            "queued": int(counts.get("pending", 0)),
            "running": int(counts.get("running", 0)),
            "succeeded": int(counts.get("succeeded", 0)),
            "failed": int(counts.get("failed", 0)),
            **{
                key: value
                for key, value in (run.stats or {}).items()
                if key == "batch_hash" or key in {"created", "updated", "unchanged", "deleted"}
            },
        }
        run.stats = stats
        if stats["queued"] or stats["running"]:
            run.status = "running"
        elif stats["failed"]:
            run.status = "failed"
            run.completed_at = datetime.now(UTC)
            run.error = await db.scalar(
                select(KnowledgeSyncItem.error)
                .where(
                    KnowledgeSyncItem.run_id == run_id,
                    KnowledgeSyncItem.status == "failed",
                    KnowledgeSyncItem.error.is_not(None),
                )
                .order_by(KnowledgeSyncItem.completed_at, KnowledgeSyncItem.created_at)
                .limit(1)
            )
            if connector is not None:
                connector.last_error = run.error
        else:
            run.status = "succeeded"
            run.completed_at = datetime.now(UTC)
            run.error = None
            if connector is not None:
                connector.sync_cursor = run.cursor_after
                connector.last_sync_at = run.completed_at
                connector.last_error = None
        await db.commit()


async def _increment_run_stat(run_id: str, key: str) -> None:
    async with AsyncSessionLocal() as db:
        run = await db.get(KnowledgeSyncRun, run_id)
        if run is None:
            return
        stats = dict(run.stats or {})
        stats[key] = int(stats.get(key, 0)) + 1
        run.stats = stats
        await db.commit()


async def execute_sync_item(item_id: str) -> dict[str, Any]:
    """幂等执行单个 Snapshot；ACL 先于编译任务持久化。"""
    async with AsyncSessionLocal() as db:
        item = await db.get(KnowledgeSyncItem, item_id)
        if item is None:
            raise ValueError("knowledge_sync_item_not_found")
        connector = await db.get(KnowledgeConnector, item.connector_id)
        if connector is None or connector.status != "active":
            raise ValueError("knowledge_connector_not_active")
        space = await db.get(KnowledgeSpace, connector.space_id)
        if space is None or space.status != "active":
            raise ValueError("knowledge_space_not_active")
        external_ref = f"{connector.id}:{item.external_id}"
        source = (
            await db.get(KnowledgeSource, item.source_id)
            if item.source_id
            else await db.scalar(
                select(KnowledgeSource).where(
                    KnowledgeSource.connector_id == connector.id,
                    KnowledgeSource.external_ref == external_ref,
                    KnowledgeSource.tenant_id == item.tenant_id,
                    KnowledgeSource.workspace_id == item.workspace_id,
                )
            )
        )
        if item.deleted:
            if source is not None and source.deleted_at is None:
                await withdraw_source(
                    db,
                    source=source,
                    decided_by=connector.owner_id,
                    reason="source_connector_deleted",
                )
                await db.commit()
                await _increment_run_stat(item.run_id, "deleted")
            return {"outcome": "deleted", "source_id": source.id if source else None}

        content_changed = (
            source is None
            or source.content_hash != item.content_hash
            or source.deleted_at is not None
        )
        document_id = item.document_id or (source.document_id if source else None)
        document = await db.get(Document, document_id) if document_id else None
        created = source is None
        if content_changed:
            if document is None:
                document = Document(
                    id=str(uuid.uuid4()),
                    owner_id=connector.owner_id,
                    tenant_id=item.tenant_id,
                    workspace_id=item.workspace_id,
                    title=item.title,
                    file_type=item.content_type,
                    file_size=len(item.content.encode("utf-8")),
                    version=1,
                    status="pending",
                    chunk_strategy=1,
                )
                db.add(document)
                await db.flush()
                item.document_id = document.id
                await db.commit()
            elif not (
                document.status == "ready"
                and document.content is not None
                and item.content_hash
                == hashlib.sha256(document.content.encode("utf-8")).hexdigest()
            ):
                document.title = item.title
                document.file_type = item.content_type
                document.file_size = len(item.content.encode("utf-8"))
                document.version += 1
            document.doc_metadata = json.dumps(
                _metadata(item, connector, space), ensure_ascii=False
            )
            if document.status != "ready" or document.content != item.content:
                await ingest_document(db, document, item.content)
        elif document is None:
            raise ValueError("knowledge_source_document_missing")

        if source is None:
            source = KnowledgeSource(
                id=stable_id("source", f"{item.tenant_id}:{item.workspace_id}:{document.id}"),
                document_id=document.id,
                owner_id=connector.owner_id,
                tenant_id=item.tenant_id,
                workspace_id=item.workspace_id,
                space_id=connector.space_id,
                connector_id=connector.id,
                steward_id=connector.owner_id,
                source_type=connector.connector_type,
                external_ref=external_ref,
                title=item.title,
                content_hash=item.content_hash,
                authority=item.authority or KnowledgeAuthority.EXTERNAL.value,
                classification=item.classification or space.default_classification,
                source_system=connector.connector_type,
                sync_status="current",
                status=KnowledgeStatus.COMPILING.value,
            )
            db.add(source)
            await db.flush()
            item.source_id = source.id
        source.document_id = document.id
        source.space_id = connector.space_id
        source.connector_id = connector.id
        source.external_ref = external_ref
        source.source_type = connector.connector_type
        source.title = item.title
        source.content_hash = item.content_hash
        source.status = source_status_during_refresh(
            source.active_version_id, KnowledgeStatus.COMPILING
        )
        source.source_system = connector.connector_type
        source.classification = item.classification or space.default_classification
        source.authority = item.authority
        source.effective_from = item.effective_from
        source.effective_to = item.effective_to
        source.sync_status = "current"
        source.deleted_at = None
        source.source_metadata = {
            **(source.source_metadata or {}),
            **(item.source_metadata or {}),
            "connector_external_id": item.external_id,
        }
        await db.execute(
            delete(KnowledgeSourcePermission).where(
                KnowledgeSourcePermission.source_id == source.id
            )
        )
        for acl in item.acl_snapshot or []:
            if not isinstance(acl, dict) or not acl.get("subject_id"):
                continue
            db.add(
                KnowledgeSourcePermission(
                    id=str(uuid.uuid4()),
                    source_id=source.id,
                    tenant_id=item.tenant_id,
                    workspace_id=item.workspace_id,
                    subject_type=str(acl.get("subject_type") or "user"),
                    subject_id=str(acl["subject_id"]),
                    permission=str(acl.get("permission") or "view"),
                    inherited=bool(acl.get("inherited")),
                    external_ref=acl.get("external_ref"),
                    expires_at=(
                        datetime.fromisoformat(str(acl["expires_at"]))
                        if acl.get("expires_at")
                        else None
                    ),
                )
            )
        await db.commit()
        if content_changed:
            await enqueue_document_compile(document.id)
            outcome = "created" if created else "updated"
        else:
            outcome = "unchanged"
        await _increment_run_stat(item.run_id, outcome)
        return {"outcome": outcome, "source_id": source.id, "document_id": document.id}


async def process_pending_sync_items(*, limit: int = 4, worker_id: str | None = None) -> int:
    worker = worker_id or f"knowledge-sync-{os.getpid()}"
    reclaim_minutes = max(1, int(settings.knowledge_sync_reclaim_minutes))
    max_attempts = max(1, int(settings.knowledge_sync_max_attempts))
    processed = 0
    for _ in range(max(1, limit)):
        claimed: tuple[str, str, str] | None = None
        expired_run_ids: set[str] = set()
        async with AsyncSessionLocal() as db:
            cutoff = datetime.now(UTC) - timedelta(minutes=reclaim_minutes)
            await db.execute(
                update(KnowledgeSyncItem)
                .where(
                    KnowledgeSyncItem.status == "running",
                    KnowledgeSyncItem.started_at.is_not(None),
                    KnowledgeSyncItem.started_at < cutoff,
                    KnowledgeSyncItem.attempts < max_attempts,
                )
                .values(status="pending", locked_by=None, started_at=None)
            )
            exhausted = await db.execute(
                update(KnowledgeSyncItem)
                .where(
                    KnowledgeSyncItem.status == "running",
                    KnowledgeSyncItem.started_at.is_not(None),
                    KnowledgeSyncItem.started_at < cutoff,
                    KnowledgeSyncItem.attempts >= max_attempts,
                )
                .values(
                    status="failed",
                    locked_by=None,
                    completed_at=datetime.now(UTC),
                    error="knowledge_sync_worker_lease_expired",
                )
                .returning(KnowledgeSyncItem.run_id)
            )
            expired_run_ids.update(str(value) for value in exhausted.scalars())

            earlier_run = aliased(KnowledgeSyncRun)
            blocking_earlier_run = exists(
                select(earlier_run.id).where(
                    earlier_run.connector_id == KnowledgeSyncItem.connector_id,
                    earlier_run.id != KnowledgeSyncRun.id,
                    earlier_run.status.in_(("pending", "running", "failed")),
                    or_(
                        earlier_run.started_at < KnowledgeSyncRun.started_at,
                        and_(
                            earlier_run.started_at == KnowledgeSyncRun.started_at,
                            earlier_run.id < KnowledgeSyncRun.id,
                        ),
                    ),
                )
            )
            item = await db.scalar(
                select(KnowledgeSyncItem)
                .join(KnowledgeConnector, KnowledgeSyncItem.connector_id == KnowledgeConnector.id)
                .join(KnowledgeSyncRun, KnowledgeSyncItem.run_id == KnowledgeSyncRun.id)
                .where(
                    KnowledgeSyncItem.status == "pending",
                    KnowledgeSyncItem.attempts < max_attempts,
                    KnowledgeConnector.status == "active",
                    ~blocking_earlier_run,
                )
                .order_by(KnowledgeSyncRun.started_at, KnowledgeSyncItem.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if item is not None:
                item.status = "running"
                item.attempts += 1
                item.locked_by = worker
                item.started_at = datetime.now(UTC)
                item.error = None
                run = await db.get(KnowledgeSyncRun, item.run_id)
                if run is not None:
                    run.status = "running"
                claimed = (item.id, item.run_id, item.connector_id)
            await db.commit()

        for expired_run_id in expired_run_ids:
            await _refresh_run(expired_run_id)
        if claimed is None:
            break
        item_id, run_id, connector_id = claimed
        try:
            await execute_sync_item(item_id)
            async with AsyncSessionLocal() as db:
                completed = await db.get(KnowledgeSyncItem, item_id)
                if completed is not None:
                    completed.status = "succeeded"
                    completed.completed_at = datetime.now(UTC)
                    completed.locked_by = None
                    completed.error = None
                    await db.commit()
        except Exception as exc:  # noqa: BLE001
            async with AsyncSessionLocal() as db:
                failed = await db.get(KnowledgeSyncItem, item_id)
                connector = await db.get(KnowledgeConnector, connector_id)
                if failed is not None:
                    failed.status = "failed"
                    failed.completed_at = datetime.now(UTC)
                    failed.locked_by = None
                    failed.error = str(exc)[:2000]
                if connector is not None:
                    connector.last_error = str(exc)[:2000]
                await db.commit()
        await _refresh_run(run_id)
        processed += 1
    return processed


async def retry_sync_run(run_id: str) -> dict[str, int | str]:
    async with AsyncSessionLocal() as db:
        run = await db.get(KnowledgeSyncRun, run_id)
        if run is None:
            raise ValueError("knowledge_sync_run_not_found")
        result = await db.execute(
            update(KnowledgeSyncItem)
            .where(
                KnowledgeSyncItem.run_id == run_id,
                KnowledgeSyncItem.status == "failed",
            )
            .values(
                status="pending",
                attempts=0,
                error=None,
                completed_at=None,
                started_at=None,
                locked_by=None,
            )
        )
        run.status = "pending"
        run.completed_at = None
        run.error = None
        count = int(result.rowcount or 0)
        await db.commit()
        return {"run_id": run_id, "requeued": count, "status": run.status}
