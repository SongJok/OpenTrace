"""数据层到受治理 Wiki 层的统一摄入入口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from infra.storage.database import AsyncSessionLocal
from infra.storage.models import Document
from knowledge.compiler import compile_document_knowledge
from knowledge.jobs import enqueue_document_compile


@dataclass(slots=True)
class IngestResult:
    workspace_id: str
    submitted: int = 0
    compiled: int = 0
    skipped: int = 0
    failed: int = 0
    operations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def created(self) -> int:
        return self.compiled or self.submitted

    @property
    def updated(self) -> int:
        return sum(item.get("reason") == "content_unchanged" for item in self.operations)

    @property
    def links(self) -> int:
        return sum(int(item.get("relation_count", 0) or 0) for item in self.operations)


class IngestPipeline:
    """复用正式编译器与持久化队列，不维护第二套摄入状态。"""

    async def ingest_document(self, document_id: str, *, immediate: bool = False) -> dict[str, Any]:
        if immediate:
            return await compile_document_knowledge(document_id)
        return await enqueue_document_compile(document_id)

    async def ingest_workspace(
        self,
        *,
        workspace_id: str,
        tenant_id: str = "default",
        owner_id: str | None = None,
        immediate: bool = False,
        limit: int = 100,
    ) -> IngestResult:
        conditions = [
            Document.tenant_id == tenant_id,
            Document.workspace_id == workspace_id,
            Document.status == "ready",
        ]
        if owner_id:
            conditions.append(Document.owner_id == owner_id)
        async with AsyncSessionLocal() as db:
            document_ids = list(
                (
                    await db.execute(
                        select(Document.id)
                        .where(*conditions)
                        .order_by(Document.updated_at.asc())
                        .limit(max(1, min(limit, 1000)))
                    )
                ).scalars()
            )

        result = IngestResult(workspace_id=workspace_id)
        for document_id in document_ids:
            try:
                operation = await self.ingest_document(document_id, immediate=immediate)
                result.operations.append(operation)
                status = operation.get("status")
                if status == "succeeded":
                    result.compiled += 1
                elif status == "queued":
                    result.submitted += 1
                else:
                    result.skipped += 1
            except Exception as exc:  # noqa: BLE001
                result.failed += 1
                result.operations.append(
                    {"document_id": document_id, "status": "failed", "error": str(exc)}
                )
        return result
