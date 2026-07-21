"""Durable knowledge compilation queue backed by PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update

from infra.storage.database import AsyncSessionLocal
from infra.storage.models import (
    Document,
    KnowledgeCompilationJob,
    KnowledgeSource,
    KnowledgeSourceVersion,
)
from knowledge.compiler import compile_document_knowledge, content_hash, stable_id
from knowledge.domain import (
    KNOWLEDGE_COMPILER_VERSION,
    KnowledgeAuthority,
    KnowledgeStatus,
    source_status_during_refresh,
)


async def enqueue_document_compile(document_id: str) -> dict[str, Any]:
    """Create one durable pending job for the current document revision."""
    async with AsyncSessionLocal() as db:
        document = await db.get(Document, document_id)
        if document is None or document.status != "ready":
            return {"status": "skipped", "reason": "document_not_ready", "document_id": document_id}

        digest = content_hash(document.content or "")
        source = await db.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.document_id == document.id,
                KnowledgeSource.tenant_id == document.tenant_id,
                KnowledgeSource.workspace_id == document.workspace_id,
            )
        )
        if source is None:
            source = KnowledgeSource(
                id=stable_id("source", f"{document.tenant_id}:{document.workspace_id}:{document.id}"),
                document_id=document.id,
                owner_id=document.owner_id,
                tenant_id=document.tenant_id,
                workspace_id=document.workspace_id,
                project_id=document.project_id,
                source_type="document",
                external_ref=f"document:{document.id}",
                title=document.title,
                content_hash=digest,
                authority=KnowledgeAuthority.CONTEXTUAL.value,
                status=KnowledgeStatus.COMPILING.value,
                source_metadata={"file_type": document.file_type, "document_version": document.version},
            )
            db.add(source)
            await db.flush()
        else:
            source.content_hash = digest
            source.title = document.title
            source.project_id = document.project_id

        compiled_revision = await db.scalar(
            select(KnowledgeSourceVersion.id).where(
                KnowledgeSourceVersion.source_id == source.id,
                KnowledgeSourceVersion.content_hash == digest,
                KnowledgeSourceVersion.compiler_version == KNOWLEDGE_COMPILER_VERSION,
                KnowledgeSourceVersion.status.in_(["published", "review"]),
            )
        )
        if compiled_revision is not None:
            await db.commit()
            return {
                "status": "skipped",
                "reason": "content_unchanged",
                "document_id": document_id,
                "source_version_id": compiled_revision,
            }

        source.status = source_status_during_refresh(
            source.active_version_id,
            KnowledgeStatus.COMPILING,
        )

        existing = await db.scalar(
            select(KnowledgeCompilationJob)
            .where(
                KnowledgeCompilationJob.source_id == source.id,
                KnowledgeCompilationJob.status.in_(["pending", "running"]),
            )
            .order_by(KnowledgeCompilationJob.created_at.desc())
        )
        if existing is not None:
            await db.commit()
            return {"status": "queued", "job_id": existing.id, "document_id": document_id, "deduplicated": True}

        job = KnowledgeCompilationJob(
            id=str(uuid.uuid4()),
            source_id=source.id,
            owner_id=document.owner_id,
            tenant_id=document.tenant_id,
            workspace_id=document.workspace_id,
            project_id=document.project_id,
            status="pending",
            compiler_version=KNOWLEDGE_COMPILER_VERSION,
            result_metadata={"document_id": document.id, "document_version": document.version},
        )
        db.add(job)
        await db.commit()
        return {"status": "queued", "job_id": job.id, "document_id": document_id, "deduplicated": False}


async def process_pending_compile_jobs(*, limit: int = 4, worker_id: str | None = None) -> int:
    """Claim and execute a bounded batch of pending jobs.

    PostgreSQL row locks prevent two worker replicas from compiling the same
    source concurrently.  A failed job is retained as ``failed`` for the API
    and can be requeued explicitly.
    """
    worker = worker_id or f"knowledge-worker-{os.getpid()}"
    processed = 0
    for _ in range(max(1, limit)):
        async with AsyncSessionLocal() as db:
            # A worker can disappear between the claim commit and compiler
            # completion.  Requeue only old running jobs so a fresh worker can
            # recover them without racing a healthy worker.
            reclaim_minutes = max(1, int(os.getenv("KNOWLEDGE_JOB_RECLAIM_MINUTES", "10")))
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=reclaim_minutes)
            await db.execute(
                update(KnowledgeCompilationJob)
                .where(
                    KnowledgeCompilationJob.status == "running",
                    KnowledgeCompilationJob.started_at.is_not(None),
                    KnowledgeCompilationJob.started_at < cutoff,
                )
                .values(status="pending", error=None, completed_at=None)
            )
            await db.flush()
            row = (
                await db.execute(
                    select(KnowledgeCompilationJob, KnowledgeSource)
                    .join(KnowledgeSource, KnowledgeCompilationJob.source_id == KnowledgeSource.id)
                    .where(KnowledgeCompilationJob.status == "pending")
                    .order_by(KnowledgeCompilationJob.created_at.asc())
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            ).first()
            if row is None:
                break
            job, source = row
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            job.result_metadata = {**(job.result_metadata or {}), "worker_id": worker}
            await db.commit()

        try:
            if not source.document_id:
                raise ValueError("knowledge_source_has_no_document")
            await compile_document_knowledge(source.document_id, job_id=job.id)
        except Exception as exc:  # noqa: BLE001
            async with AsyncSessionLocal() as db:
                failed = await db.get(KnowledgeCompilationJob, job.id)
                if failed is not None:
                    failed.status = "failed"
                    failed.error = str(exc)[:2000]
                    failed.completed_at = datetime.now(timezone.utc)
                    await db.commit()
        processed += 1
    return processed


async def reconcile_ready_documents(*, limit: int = 200) -> dict[str, int]:
    """Recover uploads missed by background tasks and enqueue changed revisions."""
    async with AsyncSessionLocal() as db:
        document_ids = list(
            (
                await db.execute(
                    select(Document.id)
                    .where(Document.status == "ready")
                    .order_by(Document.updated_at.desc())
                    .limit(max(1, min(limit, 1000)))
                )
            ).scalars().all()
        )
    queued = 0
    for document_id in document_ids:
        result = await enqueue_document_compile(document_id)
        if result.get("status") == "queued" and not result.get("deduplicated"):
            queued += 1
    return {"scanned": len(document_ids), "queued": queued}


async def knowledge_job_loop() -> None:
    """Long-running worker loop; safe when no jobs are available."""
    interval = max(1, int(os.getenv("KNOWLEDGE_JOB_POLL_SECONDS", "2")))
    reconcile_interval = max(30, int(os.getenv("KNOWLEDGE_RECONCILE_SECONDS", "300")))
    loop = asyncio.get_running_loop()
    next_reconcile = 0.0
    while True:
        try:
            if loop.time() >= next_reconcile:
                await reconcile_ready_documents()
                next_reconcile = loop.time() + reconcile_interval
            processed = await process_pending_compile_jobs()
            if not processed:
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(interval)
