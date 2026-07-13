"""Chat-facing knowledge orchestration primitives.

This module keeps chat protocol concerns out of the compiler and provides the
session-asset -> governed-document promotion boundary.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    Attachment,
    Document,
    DocumentChunk,
    KnowledgePage,
    KnowledgeRelation,
    KnowledgeSource,
    KnowledgeSourceVersion,
    ConversationState,
    User,
)
from knowledge.compiler import content_hash
from knowledge.domain import KnowledgeStatus
from knowledge.evolution import build_evolution_proposal
from knowledge.jobs import enqueue_document_compile
from knowledge.lint import run_knowledge_lint
from knowledge.merge import resolve_merge_case
from knowledge.trace import trace_knowledge_assets


@dataclass(slots=True)
class KnowledgeActionResult:
    action: str
    status: str
    message: str
    operations: list[dict[str, Any]]
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "status": self.status,
            "message": self.message,
            "operations": self.operations,
            "data": self.data,
        }


def infer_knowledge_action(query: str) -> str:
    """Infer only explicit knowledge commands; ordinary questions remain RAG."""
    q = (query or "").strip().lower()
    if any(k in q for k in ("加入知识库", "保存到工作区", "纳入知识库", "导入知识")):
        return "ingest"
    if any(k in q for k in ("检查知识库", "知识库 lint", "知识库健康", "检查知识健康")):
        return "lint"
    if any(k in q for k in ("演化规则", "优化规则", "知识编排建议", "根据反馈优化")):
        return "evolve"
    if any(k in q for k in ("追溯引用", "来源是哪", "来自哪份文档", "知识溯源")):
        return "trace"
    if any(k in q for k in ("合并冲突", "合并这两个结论", "知识合并")):
        return "merge"
    if any(k in q for k in ("建立关联", "建立链接", "关联这两个页面", "知识链接")):
        return "link"
    return "query"


def _split_content(content: str, max_chars: int = 1800) -> list[str]:
    paragraphs = [part.strip() for part in (content or "").replace("\r\n", "\n").split("\n\n") if part.strip()]
    chunks: list[str] = []
    for paragraph in paragraphs or [content.strip()]:
        while len(paragraph) > max_chars:
            cut = paragraph.rfind("。", 0, max_chars)
            cut = cut + 1 if cut > max_chars // 2 else max_chars
            chunks.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if paragraph:
            chunks.append(paragraph)
    return chunks or [" "]


async def promote_attachment_to_document(
    db: AsyncSession,
    *,
    attachment_id: str,
    user: User,
    tenant_id: str,
    workspace_id: str,
    publish_policy: str = "review",
) -> dict[str, Any]:
    attachment = await db.scalar(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.user_id == user.id,
            Attachment.status == "active",
        )
    )
    if attachment is None:
        raise ValueError("attachment_not_found_or_forbidden")
    if not attachment.content_text or attachment.content_text.startswith("[文件解析失败"):
        raise ValueError("attachment_has_no_parseable_text")

    digest = attachment.content_hash or content_hash(attachment.content_text)
    existing_source = await db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.owner_id == user.id,
            KnowledgeSource.tenant_id == tenant_id,
            KnowledgeSource.workspace_id == workspace_id,
            KnowledgeSource.content_hash == digest,
        ).order_by(KnowledgeSource.updated_at.desc())
    )
    if existing_source is not None and existing_source.document_id:
        attachment.scope = "workspace"
        attachment.ingest_status = "published" if existing_source.status == "published" else "queued"
        attachment.promoted_document_id = existing_source.document_id
        attachment.asset_metadata = {
            **(attachment.asset_metadata or {}),
            "content_hash": digest,
            "deduplicated_to_source_id": existing_source.id,
        }
        await db.flush()
        return {
            "attachment_id": attachment.id,
            "document_id": existing_source.document_id,
            "source_id": existing_source.id,
            "status": "deduplicated",
        }

    document_id = str(uuid.uuid4())
    chunks = _split_content(attachment.content_text)
    document = Document(
        id=document_id,
        owner_id=user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        title=attachment.filename,
        file_type=attachment.file_extension or "text",
        file_size=attachment.file_size,
        content=attachment.content_text,
        chunk_count=len(chunks),
        version=1,
        status="ready",
        chunk_strategy=1,
        doc_metadata=json.dumps(
            {
                "origin": "chat_attachment",
                "attachment_id": attachment.id,
                "content_hash": digest,
                "scope": "workspace",
                "publish_policy": publish_policy,
            },
            ensure_ascii=False,
        ),
    )
    db.add(document)
    for index, text in enumerate(chunks):
        db.add(
            DocumentChunk(
                id=str(uuid.uuid4()),
                document_id=document_id,
                chunk_index=index,
                content=text,
                chunk_metadata=json.dumps({"origin": "chat_attachment", "attachment_id": attachment.id}, ensure_ascii=False),
            )
        )
    attachment.scope = "workspace"
    attachment.ingest_status = "queued"
    attachment.promoted_document_id = document_id
    attachment.asset_metadata = {
        **(attachment.asset_metadata or {}),
        "content_hash": digest,
        "promoted_at": "pending",
        "publish_policy": publish_policy,
    }
    await db.flush()
    return {
        "attachment_id": attachment.id,
        "document_id": document_id,
        "status": "queued",
    }


async def perform_knowledge_action(
    db: AsyncSession,
    *,
    action: str,
    user: User,
    tenant_id: str,
    workspace_id: str,
    attachment_ids: list[str] | None = None,
    source_ids: list[str] | None = None,
    publish_policy: str = "review",
    resolution: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> KnowledgeActionResult:
    action = action or "query"
    if action == "ingest":
        operations = []
        for attachment_id in attachment_ids or []:
            operations.append(
                await promote_attachment_to_document(
                    db,
                    attachment_id=attachment_id,
                    user=user,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    publish_policy=publish_policy,
                )
            )
        await db.commit()
        for operation in operations:
            if operation.get("document_id") and operation.get("status") == "queued":
                queued = await enqueue_document_compile(operation["document_id"])
                operation.update({"job_id": queued.get("job_id"), "status": queued.get("status", "queued")})
        return KnowledgeActionResult(action, "queued" if operations else "needs_attachment", "已提交知识摄入任务。" if operations else "请先上传或选择附件。", operations, {"count": len(operations)})

    if action == "lint":
        result = await run_knowledge_lint(db, tenant_id=tenant_id, workspace_id=workspace_id, owner_id=user.id)
        await db.commit()
        return KnowledgeActionResult(action, "completed", f"知识检查完成，发现 {result.get('open_count', 0)} 个问题。", [], result)

    if action == "evolve":
        result = await build_evolution_proposal(db, tenant_id=tenant_id, workspace_id=workspace_id, owner_id=user.id)
        await db.commit()
        return KnowledgeActionResult(action, "proposal", "已生成需要人工批准的规则演化建议。", [], result)

    if action == "link":
        page_ids = source_ids or []
        if len(page_ids) < 2:
            return KnowledgeActionResult(action, "needs_pages", "请提供至少两个知识页面 ID。", [], {})
        pages = list((await db.execute(select(KnowledgePage).where(
            KnowledgePage.id.in_(page_ids), KnowledgePage.owner_id == user.id,
            KnowledgePage.tenant_id == tenant_id, KnowledgePage.workspace_id == workspace_id,
        ))).scalars().all())
        if len(pages) != len(set(page_ids)):
            raise ValueError("knowledge_page_not_found_or_forbidden")
        version = await db.get(KnowledgeSourceVersion, pages[0].source_version_id)
        if version is None:
            raise ValueError("knowledge_page_version_not_found")
        status = KnowledgeStatus.PUBLISHED.value if publish_policy == "auto" else KnowledgeStatus.REVIEW.value
        relations = []
        for source_page, target_page, relation_type in ((pages[0], pages[1], "related_to"), (pages[1], pages[0], "related_from")):
            row = KnowledgeRelation(
                id=str(uuid.uuid4()), source_version_id=version.id, owner_id=user.id,
                tenant_id=tenant_id, workspace_id=workspace_id,
                source_page_id=source_page.id, target_page_id=target_page.id,
                relation_type=relation_type, authority="contextual", confidence=0.75,
                status=status, relation_metadata={"origin": "chat_link"},
            )
            db.add(row)
            relations.append({"id": row.id, "type": relation_type})
        await db.commit()
        return KnowledgeActionResult(action, status, "知识页面关联已提交。", relations, {})

    if action == "trace":
        trace_ids = list(source_ids or [])
        if not trace_ids and session_id:
            state = await db.scalar(select(ConversationState).where(ConversationState.session_id == session_id))
            for item in (getattr(state, "last_results", None) or []) if state is not None else []:
                if isinstance(item, dict):
                    candidates = [item]
                    if isinstance(item.get("payload"), dict):
                        candidates.append(item["payload"])
                    if isinstance(item.get("citation"), dict):
                        candidates.append(item["citation"])
                    for candidate in candidates:
                        trace_ids.extend(
                            str(candidate[key]) for key in ("claim_id", "knowledge_claim_id", "page_id", "knowledge_page_id", "relation_id", "source_id", "source_version_id")
                            if candidate.get(key)
                        )
        traced = await trace_knowledge_assets(
            db, ids=trace_ids, tenant_id=tenant_id, workspace_id=workspace_id, owner_id=user.id,
        )
        return KnowledgeActionResult(
            action, "completed" if traced else "needs_source",
            f"已解析 {len(traced)} 条可追溯证据链。" if traced else "请提供引用、页面或结论 ID。",
            traced, {"evidence_refs": traced, "source_ids": trace_ids},
        )

    if action == "merge":
        resolution = resolution or {}
        case_id = str(resolution.get("case_id") or "")
        if case_id:
            applied = await resolve_merge_case(
                db, case_id=case_id, owner_id=user.id, tenant_id=tenant_id,
                workspace_id=workspace_id, resolution=resolution,
            )
            await db.commit()
            return KnowledgeActionResult(action, applied["status"], "冲突审核已应用。", [applied], applied)
        from infra.storage.models import KnowledgeMergeCase
        cases = list((await db.execute(select(KnowledgeMergeCase).where(
            KnowledgeMergeCase.owner_id == user.id, KnowledgeMergeCase.tenant_id == tenant_id,
            KnowledgeMergeCase.workspace_id == workspace_id, KnowledgeMergeCase.status == "open",
        ).order_by(KnowledgeMergeCase.created_at.desc()).limit(50))).scalars().all())
        data = [{"id": row.id, "entity_key": row.entity_key, "conflict_type": row.conflict_type,
                 "candidate_ids": row.candidate_ids, "resolution": row.resolution} for row in cases]
        return KnowledgeActionResult(action, "needs_review" if data else "completed",
                                     f"发现 {len(data)} 个待审核冲突。" if data else "当前没有待审核冲突。", data, {"merge_cases": data})

    return KnowledgeActionResult(action, "delegated", "知识查询将由统一 RAG 路由执行。", [], {})
