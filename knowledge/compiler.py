"""Deterministic document-to-knowledge compiler with explicit provenance."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infra.config.settings import settings
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import (
    Attachment,
    Document,
    DocumentChunk,
    KnowledgeClaim,
    KnowledgeCompilationJob,
    KnowledgePage,
    KnowledgeRelation,
    KnowledgeReviewTask,
    KnowledgeSource,
    KnowledgeSourceVersion,
    KnowledgeSpace,
)
from knowledge.domain import (
    KNOWLEDGE_COMPILER_VERSION,
    KnowledgeAuthority,
    KnowledgeStatus,
    KnowledgeType,
    source_is_withdrawn,
    source_status_during_refresh,
)
from knowledge.rules import active_rule, active_rule_version, validate_compiled_payload

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？.!?；;])\s*|\n+")
_SPACE = re.compile(r"\s+")


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def stable_id(namespace: str, value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"opentrace:{namespace}:{value}"))


def slugify(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", (value or "").lower()).strip("-")
    return (normalized[:220] or fallback).strip("-")


def _chunk_metadata(chunk: DocumentChunk) -> dict[str, Any]:
    try:
        data = json.loads(chunk.chunk_metadata or "{}")
        return data if isinstance(data, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _page_type(title: str, content: str) -> str:
    text = f"{title}\n{content}".lower()
    if title.rstrip().endswith(("?", "？")) or any(
        token in title for token in ("什么是", "为什么", "如何", "怎么")
    ):
        return KnowledgeType.QUESTION.value
    if any(token in text for token in ("步骤", "流程", "如何", "操作", "申请", "办理")):
        return KnowledgeType.PROCEDURE.value
    if any(token in text for token in ("政策", "制度", "规定", "规范", "条例")):
        return KnowledgeType.POLICY.value
    if any(token in text for token in ("指标", "口径", "公式", "计算")):
        return KnowledgeType.METRIC.value
    if any(token in text for token in ("案例", "复盘", "事故", "故障", "实践")):
        return KnowledgeType.CASE.value
    if any(token in title for token in ("术语", "名词", "定义")):
        return KnowledgeType.TERM.value
    return KnowledgeType.CONCEPT.value


def _summary(text: str, limit: int = 420) -> str:
    text = _SPACE.sub(" ", text or "").strip()
    return text[:limit]


def compile_payload(
    *,
    document_id: str,
    source_version_id: str,
    title: str,
    chunks: list[DocumentChunk],
    orchestration: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build schema-shaped pages, claims and relations without model calls.

    The deterministic compiler is intentionally conservative: every generated
    claim is copied from a source sentence and keeps its originating chunk.
    More capable AI compilers can be added as later compiler versions without
    changing the data contract.
    """

    config = orchestration or {}
    summary_limit = max(80, min(int(config.get("summary_length", 420)), 2000))
    content_limit = max(1000, min(int(config.get("content_limit", 16000)), 100000))
    min_claim_length = max(4, min(int(config.get("min_claim_length", 8)), 200))
    max_claims_per_page = max(1, min(int(config.get("max_claims_per_page", 12)), 100))
    page_type_keywords = config.get("page_type_keywords") or {}

    grouped: dict[str, list[DocumentChunk]] = defaultdict(list)
    for chunk in chunks:
        heading = str(_chunk_metadata(chunk).get("heading") or "").strip() or title
        grouped[heading].append(chunk)

    pages: list[dict[str, Any]] = []
    all_content = "\n".join(chunk.content for chunk in chunks if chunk.content).strip()
    overview_id = stable_id("page", f"{source_version_id}:overview")
    pages.append(
        {
            "id": overview_id,
            "title": title,
            "slug": "overview",
            "page_type": KnowledgeType.OVERVIEW.value,
            "content": all_content[:content_limit] or title,
            "summary": _summary(all_content, summary_limit),
            "chunk_ids": [chunk.id for chunk in chunks],
        }
    )

    for index, (heading, section_chunks) in enumerate(grouped.items(), start=1):
        section_content = "\n".join(
            chunk.content for chunk in section_chunks if chunk.content
        ).strip()
        if not section_content:
            continue
        slug = slugify(heading, f"section-{index}")
        page_id = stable_id("page", f"{source_version_id}:{slug}")
        detected_type = _page_type(heading, section_content)
        lowered = f"{heading}\n{section_content}".lower()
        for configured_type, keywords in page_type_keywords.items():
            if any(str(keyword).lower() in lowered for keyword in (keywords or [])):
                detected_type = str(configured_type)
                break
        pages.append(
            {
                "id": page_id,
                "title": heading[:255],
                "slug": slug,
                "page_type": detected_type,
                "content": section_content[:content_limit],
                "summary": _summary(section_content, summary_limit),
                "chunk_ids": [chunk.id for chunk in section_chunks],
            }
        )

    claims: list[dict[str, Any]] = []
    for page in pages:
        if page["page_type"] == KnowledgeType.OVERVIEW.value:
            continue
        page_chunk_ids = set(page["chunk_ids"])
        page_claim_hashes: set[str] = set()
        claim_count = 0
        for chunk in chunks:
            if chunk.id not in page_chunk_ids:
                continue
            for sentence in _SENTENCE_SPLIT.split(chunk.content or ""):
                text = _SPACE.sub(" ", sentence).strip()
                if len(text) < min_claim_length:
                    continue
                normalized = text.lower()
                claim_digest = content_hash(normalized)
                # 同一章节可能因分块重叠或原文重复出现相同句子。Claim 主键按
                # 页面与内容稳定生成，因此只保留首次出现的证据，避免批量写入
                # 产生重复主键，同时让重新编译仍保持确定性。
                if claim_digest in page_claim_hashes:
                    continue
                page_claim_hashes.add(claim_digest)
                claims.append(
                    {
                        "id": stable_id("claim", f"{page['id']}:{claim_digest}"),
                        "page_id": page["id"],
                        "text": text[:1500],
                        "normalized_text": normalized[:1500],
                        "claim_hash": claim_digest,
                        "evidence_chunk_id": chunk.id,
                        "evidence_start": (chunk.content or "").find(sentence),
                        "evidence_end": (chunk.content or "").find(sentence) + len(sentence),
                        "claim_type": (
                            "procedure"
                            if page["page_type"] == KnowledgeType.PROCEDURE.value
                            else "fact"
                        ),
                    }
                )
                claim_count += 1
                if claim_count >= max_claims_per_page:
                    break
            if claim_count >= max_claims_per_page:
                break

    relations: list[dict[str, Any]] = []
    relation_keys: set[tuple[str, str, str]] = set()

    def add_relation(source_page_id: str, target_page_id: str, relation_type: str) -> None:
        key = (source_page_id, target_page_id, relation_type)
        if key in relation_keys or source_page_id == target_page_id:
            return
        relation_keys.add(key)
        relations.append(
            {
                "id": stable_id(
                    "relation",
                    f"{source_page_id}:{target_page_id}:{relation_type}",
                ),
                "source_page_id": source_page_id,
                "target_page_id": target_page_id,
                "relation_type": relation_type,
            }
        )

    for page in pages:
        if page["id"] == overview_id:
            continue
        add_relation(overview_id, page["id"], "contains")
        add_relation(page["id"], overview_id, "part_of")

    # 在确定性编译阶段建立 Obsidian 风格的语义链接种子。只在一个章节正文
    # 明确提到另一章节标题时建边，避免模型推断造成不可追溯的图谱关系。
    section_pages = [page for page in pages if page["id"] != overview_id]
    for source_page in section_pages:
        source_text = source_page["content"].lower()
        for target_page in section_pages:
            target_title = target_page["title"].strip()
            if (
                source_page["id"] != target_page["id"]
                and len(target_title) >= 2
                and target_title.lower() in source_text
            ):
                add_relation(source_page["id"], target_page["id"], "references")
                add_relation(target_page["id"], source_page["id"], "referenced_by")
    return pages, claims, relations


async def compile_document_knowledge(document_id: str, job_id: str | None = None) -> dict[str, Any]:
    """Background-compatible entry point used after document ingestion."""

    async with AsyncSessionLocal() as db:
        try:
            result = await compile_document_knowledge_in_session(db, document_id, job_id=job_id)
            if result.get("status") == "succeeded":
                from knowledge.graph import link_workspace_pages
                from knowledge.lint import run_knowledge_lint

                document = await db.get(Document, document_id)
                if document is not None:
                    await link_workspace_pages(
                        db,
                        tenant_id=document.tenant_id,
                        workspace_id=document.workspace_id,
                        owner_id=document.owner_id,
                    )
                    await run_knowledge_lint(
                        db,
                        tenant_id=document.tenant_id,
                        workspace_id=document.workspace_id,
                        owner_id=document.owner_id,
                    )
            await db.commit()
            return result
        except Exception:
            # flush/commit 失败后 Session 必须先回滚，避免 PendingRollbackError 掩盖根因。
            await db.rollback()
            raise


async def compile_document_knowledge_in_session(
    db: AsyncSession,
    document_id: str,
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    document = await db.get(Document, document_id)
    if document is None or document.status != "ready":
        return {"status": "skipped", "reason": "document_not_ready", "document_id": document_id}

    digest = content_hash(document.content or "")
    try:
        document_metadata = json.loads(document.doc_metadata or "{}")
    except (TypeError, json.JSONDecodeError):
        document_metadata = {}
    job = await db.get(KnowledgeCompilationJob, job_id) if job_id else None
    source_result = await db.execute(
        select(KnowledgeSource)
        .where(
            KnowledgeSource.document_id == document.id,
            KnowledgeSource.tenant_id == document.tenant_id,
            KnowledgeSource.workspace_id == document.workspace_id,
        )
        .with_for_update()
    )
    source = source_result.scalar_one_or_none()
    if source is not None and source_is_withdrawn(
        status=source.status,
        sync_status=source.sync_status,
        deleted_at=source.deleted_at,
    ):
        if job is not None:
            job.status = "succeeded"
            job.completed_at = datetime.now(UTC)
            job.error = None
            job.result_metadata = {
                **(job.result_metadata or {}),
                "document_id": document.id,
                "reason": "source_withdrawn",
            }
        return {
            "status": "skipped",
            "reason": "source_withdrawn",
            "document_id": document.id,
            "source_id": source.id,
        }
    if source is not None and source.content_hash == digest and source.active_version_id:
        active_version = await db.get(KnowledgeSourceVersion, source.active_version_id)
        if (
            active_version is not None
            and active_version.content_hash == digest
            and active_version.status == KnowledgeStatus.PUBLISHED.value
        ):
            if job is not None:
                job.status = "succeeded"
                job.source_id = source.id
                job.source_version_id = active_version.id
                job.completed_at = datetime.now(UTC)
                job.error = None
                job.result_metadata = {
                    **(job.result_metadata or {}),
                    "document_id": document.id,
                    "source_version_id": active_version.id,
                    "reason": "content_unchanged",
                }
                source.status = KnowledgeStatus.PUBLISHED.value
            return {
                "status": "skipped",
                "reason": "content_unchanged",
                "document_id": document.id,
                "source_id": source.id,
                "source_version_id": active_version.id,
            }
    if source is None:
        source = KnowledgeSource(
            id=stable_id("source", f"{document.tenant_id}:{document.workspace_id}:{document.id}"),
            document_id=document.id,
            owner_id=document.owner_id,
            tenant_id=document.tenant_id,
            workspace_id=document.workspace_id,
            space_id=document_metadata.get("knowledge_space_id"),
            steward_id=document_metadata.get("knowledge_steward_id") or document.owner_id,
            source_type="document",
            external_ref=f"document:{document.id}",
            title=document.title,
            content_hash=digest,
            authority=str(
                document_metadata.get("knowledge_authority") or KnowledgeAuthority.CONTEXTUAL.value
            ),
            classification=str(document_metadata.get("classification") or "internal"),
            source_system=str(document_metadata.get("source_system") or "upload"),
            status=KnowledgeStatus.COMPILING.value,
            source_metadata={"file_type": document.file_type, "document_version": document.version},
        )
        db.add(source)
        await db.flush()
    else:
        source.title = document.title
        source.content_hash = digest
        source.status = source_status_during_refresh(
            source.active_version_id,
            KnowledgeStatus.COMPILING,
        )
        source.space_id = source.space_id or document_metadata.get("knowledge_space_id")
        source.steward_id = (
            source.steward_id or document_metadata.get("knowledge_steward_id") or document.owner_id
        )
        source.classification = str(
            document_metadata.get("classification") or source.classification or "internal"
        )
        source.source_system = str(
            document_metadata.get("source_system") or source.source_system or "upload"
        )
        source.deleted_at = None
        source.sync_status = "current"
        source.source_metadata = {
            **(source.source_metadata or {}),
            "file_type": document.file_type,
            "document_version": document.version,
        }

    version_result = await db.execute(
        select(KnowledgeSourceVersion).where(
            KnowledgeSourceVersion.source_id == source.id,
            KnowledgeSourceVersion.version_number == document.version,
        )
    )
    version = version_result.scalar_one_or_none()
    if job is None:
        job = KnowledgeCompilationJob(
            id=str(uuid.uuid4()),
            source_id=source.id,
            source_version_id=version.id if version else None,
            owner_id=document.owner_id,
            tenant_id=document.tenant_id,
            workspace_id=document.workspace_id,
            status="running",
            compiler_version=KNOWLEDGE_COMPILER_VERSION,
            started_at=datetime.now(UTC),
        )
        db.add(job)
    else:
        job.status = "running"
        job.source_id = source.id
        job.owner_id = document.owner_id
        job.tenant_id = document.tenant_id
        job.workspace_id = document.workspace_id
        job.compiler_version = KNOWLEDGE_COMPILER_VERSION
        job.started_at = job.started_at or datetime.now(UTC)

    try:
        space = await db.get(KnowledgeSpace, source.space_id) if source.space_id else None
        requested_publish_policy = str(document_metadata.get("publish_policy") or "").lower()
        if requested_publish_policy == "review":
            publication_status = KnowledgeStatus.REVIEW.value
        elif requested_publish_policy == "auto":
            publication_status = KnowledgeStatus.PUBLISHED.value
        elif space is not None:
            publication_status = (
                KnowledgeStatus.PUBLISHED.value
                if space.publish_policy == "auto"
                else KnowledgeStatus.REVIEW.value
            )
        else:
            publication_status = (
                KnowledgeStatus.PUBLISHED.value
                if getattr(settings, "knowledge_auto_publish", True)
                else KnowledgeStatus.REVIEW.value
            )
        rule_version = await active_rule_version(
            db,
            tenant_id=document.tenant_id,
            workspace_id=document.workspace_id,
        )
        rule = await active_rule(
            db,
            tenant_id=document.tenant_id,
            workspace_id=document.workspace_id,
        )
        if version is None:
            version = KnowledgeSourceVersion(
                id=stable_id("source-version", f"{source.id}:{document.version}"),
                source_id=source.id,
                version_number=document.version,
                content_hash=digest,
                compiler_version=KNOWLEDGE_COMPILER_VERSION,
                status=KnowledgeStatus.COMPILING.value,
                raw_metadata={
                    "document_id": document.id,
                    "document_version": document.version,
                    "rule_version": rule_version,
                },
            )
            db.add(version)
            await db.flush()
        else:
            version.content_hash = digest
            version.status = KnowledgeStatus.COMPILING.value

        job.source_version_id = version.id
        chunks_result = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        chunks = list(chunks_result.scalars().all())
        if not chunks:
            raise ValueError("document_has_no_chunks")
        await db.execute(
            delete(KnowledgeRelation).where(KnowledgeRelation.source_version_id == version.id)
        )
        await db.execute(
            delete(KnowledgeClaim).where(KnowledgeClaim.source_version_id == version.id)
        )
        await db.execute(delete(KnowledgePage).where(KnowledgePage.source_version_id == version.id))
        pages, claims, relations = compile_payload(
            document_id=document.id,
            source_version_id=version.id,
            title=document.title,
            chunks=chunks,
            orchestration=(rule.schema_json if rule else None),
        )
        validate_compiled_payload(rule, pages=pages, claims=claims, relations=relations)
        for page in pages:
            db.add(
                KnowledgePage(
                    id=page["id"],
                    source_version_id=version.id,
                    owner_id=document.owner_id,
                    tenant_id=document.tenant_id,
                    workspace_id=document.workspace_id,
                    page_type=page["page_type"],
                    title=page["title"],
                    slug=page["slug"],
                    content=page["content"],
                    summary=page["summary"],
                    authority=KnowledgeAuthority.CONTEXTUAL.value,
                    confidence=0.72,
                    status=publication_status,
                    page_metadata={
                        "document_id": document.id,
                        "document_version": document.version,
                        "chunk_ids": page["chunk_ids"],
                        "compiler_version": KNOWLEDGE_COMPILER_VERSION,
                        "rule_version": rule_version,
                        "rule_instructions": (
                            rule.instructions[:1000] if rule and rule.instructions else None
                        ),
                    },
                )
            )
        # The persistence model intentionally keeps compiler output decoupled
        # from ORM relationships. Flush pages before dependent claims/edges so
        # PostgreSQL foreign keys remain valid under batch insert ordering.
        await db.flush()
        for claim in claims:
            db.add(
                KnowledgeClaim(
                    id=claim["id"],
                    source_version_id=version.id,
                    page_id=claim["page_id"],
                    owner_id=document.owner_id,
                    tenant_id=document.tenant_id,
                    workspace_id=document.workspace_id,
                    claim_type=claim["claim_type"],
                    text=claim["text"],
                    normalized_text=claim["normalized_text"],
                    claim_hash=claim["claim_hash"],
                    evidence_chunk_id=claim["evidence_chunk_id"],
                    evidence_start=max(0, claim["evidence_start"]),
                    evidence_end=max(0, claim["evidence_end"]),
                    authority=KnowledgeAuthority.CONTEXTUAL.value,
                    confidence=0.68,
                    status=publication_status,
                    claim_metadata={
                        "compiler_version": KNOWLEDGE_COMPILER_VERSION,
                        "rule_version": rule_version,
                    },
                )
            )
        await db.flush()
        for relation in relations:
            db.add(
                KnowledgeRelation(
                    id=relation["id"],
                    source_version_id=version.id,
                    owner_id=document.owner_id,
                    tenant_id=document.tenant_id,
                    workspace_id=document.workspace_id,
                    source_page_id=relation["source_page_id"],
                    target_page_id=relation["target_page_id"],
                    relation_type=relation["relation_type"],
                    authority=KnowledgeAuthority.CONTEXTUAL.value,
                    confidence=0.9,
                    status=publication_status,
                    relation_metadata={
                        "compiler_version": KNOWLEDGE_COMPILER_VERSION,
                        "rule_version": rule_version,
                    },
                )
            )
        await db.flush()

        if (
            publication_status == KnowledgeStatus.PUBLISHED.value
            and source.active_version_id
            and source.active_version_id != version.id
        ):
            previous = await db.get(KnowledgeSourceVersion, source.active_version_id)
            if previous is not None:
                previous.status = KnowledgeStatus.ARCHIVED.value
                for model in (KnowledgePage, KnowledgeClaim, KnowledgeRelation):
                    await db.execute(
                        update(model)
                        .where(model.source_version_id == previous.id)
                        .values(status=KnowledgeStatus.ARCHIVED.value)
                    )
        version.status = publication_status
        version.compiled_at = datetime.now(UTC)
        if publication_status == KnowledgeStatus.REVIEW.value:
            review_task = await db.scalar(
                select(KnowledgeReviewTask).where(
                    KnowledgeReviewTask.source_version_id == version.id
                )
            )
            if review_task is None:
                review_task = KnowledgeReviewTask(
                    id=str(uuid.uuid4()),
                    source_version_id=version.id,
                    space_id=source.space_id,
                    tenant_id=document.tenant_id,
                    workspace_id=document.workspace_id,
                    status="pending",
                    required_role="publisher",
                    requested_by=document.owner_id,
                )
                db.add(review_task)
            else:
                review_task.status = "pending"
                review_task.decided_by = None
                review_task.decided_at = None
                review_task.decision_comment = None
            review_task.diff_summary = {
                "previous_version_id": source.active_version_id,
                "pages": len(pages),
                "claims": len(claims),
                "relations": len(relations),
                "content_hash": digest,
            }
        if publication_status == KnowledgeStatus.PUBLISHED.value:
            source.active_version_id = version.id
            source.status = KnowledgeStatus.PUBLISHED.value
            if space is not None:
                source.review_due_at = datetime.now(UTC) + timedelta(
                    days=max(1, space.review_cycle_days)
                )
        else:
            # Keep the previous active revision queryable while a new
            # revision waits for review.
            source.status = (
                KnowledgeStatus.PUBLISHED.value
                if source.active_version_id
                else KnowledgeStatus.REVIEW.value
            )
        job.status = "succeeded"
        job.completed_at = datetime.now(UTC)
        job.result_metadata = {
            "pages": len(pages),
            "claims": len(claims),
            "relations": len(relations),
            "document_id": document.id,
            "source_version": document.version,
            "rule_version": rule_version,
        }
        try:
            attachment_id = document_metadata.get("attachment_id")
            if attachment_id:
                attachment = await db.get(Attachment, attachment_id)
                if attachment is not None:
                    attachment.ingest_status = (
                        "published"
                        if publication_status == KnowledgeStatus.PUBLISHED.value
                        else "review"
                    )
                    attachment.promoted_document_id = document.id
                    attachment.asset_metadata = {
                        **(attachment.asset_metadata or {}),
                        "source_id": source.id,
                        "source_version_id": version.id,
                        "rule_version": rule_version,
                    }
        except Exception:
            pass
        return {
            "status": "succeeded",
            "source_id": source.id,
            "source_version_id": version.id,
            **job.result_metadata,
        }
    except Exception as exc:
        source.status = source_status_during_refresh(
            source.active_version_id,
            KnowledgeStatus.ERROR,
        )
        job.status = "failed"
        job.error = str(exc)[:2000]
        job.completed_at = datetime.now(UTC)
        raise
