"""Traceable evidence-chain lookup for chat and citation drawers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    DocumentChunk,
    KnowledgeClaim,
    KnowledgePage,
    KnowledgeRelation,
    KnowledgeSource,
    KnowledgeSourceVersion,
)


def _chain(source: KnowledgeSource, version: KnowledgeSourceVersion, *, page_id: str | None = None,
           claim_id: str | None = None, relation_id: str | None = None,
           chunk_id: str | None = None, start: int | None = None, end: int | None = None) -> dict[str, Any]:
    return {
        "source_id": source.id,
        "source_version_id": version.id,
        "document_id": source.document_id,
        "page_id": page_id,
        "claim_id": claim_id,
        "relation_id": relation_id,
        "chunk_id": chunk_id,
        "evidence_start": start,
        "evidence_end": end,
        "source_title": source.title,
        "source_status": source.status,
        "version_number": version.version_number,
    }


async def trace_knowledge_assets(
    db: AsyncSession,
    *,
    ids: list[str],
    tenant_id: str,
    workspace_id: str,
    owner_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Resolve page/claim/relation/source IDs into complete evidence chains."""
    wanted = list(dict.fromkeys(str(item) for item in ids if item))[:limit]
    if not wanted:
        return []
    out: list[dict[str, Any]] = []

    claims = list((await db.execute(select(KnowledgeClaim).where(
        KnowledgeClaim.id.in_(wanted), KnowledgeClaim.tenant_id == tenant_id,
        KnowledgeClaim.workspace_id == workspace_id, KnowledgeClaim.owner_id == owner_id,
    ))).scalars().all())
    pages = list((await db.execute(select(KnowledgePage).where(
        KnowledgePage.id.in_(wanted), KnowledgePage.tenant_id == tenant_id,
        KnowledgePage.workspace_id == workspace_id, KnowledgePage.owner_id == owner_id,
    ))).scalars().all())
    relations = list((await db.execute(select(KnowledgeRelation).where(
        KnowledgeRelation.id.in_(wanted), KnowledgeRelation.tenant_id == tenant_id,
        KnowledgeRelation.workspace_id == workspace_id, KnowledgeRelation.owner_id == owner_id,
    ))).scalars().all())
    source_rows = list((await db.execute(select(KnowledgeSource).where(
        KnowledgeSource.id.in_(wanted), KnowledgeSource.tenant_id == tenant_id,
        KnowledgeSource.workspace_id == workspace_id, KnowledgeSource.owner_id == owner_id,
    ))).scalars().all())
    direct_versions = list((await db.execute(
        select(KnowledgeSourceVersion).join(KnowledgeSource, KnowledgeSourceVersion.source_id == KnowledgeSource.id).where(
            KnowledgeSourceVersion.id.in_(wanted), KnowledgeSource.tenant_id == tenant_id,
            KnowledgeSource.workspace_id == workspace_id, KnowledgeSource.owner_id == owner_id,
        )
    )).scalars().all())
    version_ids = {item.source_version_id for item in (*claims, *pages, *relations)}
    version_ids.update(item.active_version_id for item in source_rows if item.active_version_id)
    version_rows = list((await db.execute(
        select(KnowledgeSourceVersion).where(KnowledgeSourceVersion.id.in_(version_ids))
    )).scalars().all()) if version_ids else []
    versions = {row.id: row for row in (*direct_versions, *version_rows)}
    source_ids = {row.source_id for row in versions.values()}
    source_ids.update(row.id for row in source_rows)
    sources = {row.id: row for row in source_rows}
    if source_ids:
        sources.update({row.id: row for row in (await db.execute(
            select(KnowledgeSource).where(
                KnowledgeSource.id.in_(source_ids), KnowledgeSource.tenant_id == tenant_id,
                KnowledgeSource.workspace_id == workspace_id, KnowledgeSource.owner_id == owner_id,
            )
        )).scalars().all()})
    chunk_ids = {claim.evidence_chunk_id for claim in claims if claim.evidence_chunk_id}
    chunks = {row.id: row for row in (await db.execute(
        select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))
    )).scalars().all()} if chunk_ids else {}

    for claim in claims:
        version = versions.get(claim.source_version_id)
        source = sources.get(version.source_id) if version else None
        if not version or not source:
            continue
        chunk = chunks.get(claim.evidence_chunk_id)
        out.append(_chain(source, version, page_id=claim.page_id, claim_id=claim.id,
                          chunk_id=claim.evidence_chunk_id, start=claim.evidence_start,
                          end=claim.evidence_end) | {
                              "text": claim.text, "evidence_text": chunk.content if chunk else None,
                              "kind": "claim",
                          })
    for page in pages:
        version = versions.get(page.source_version_id)
        source = sources.get(version.source_id) if version else None
        if not version or not source:
            continue
        out.append(_chain(source, version, page_id=page.id) | {
            "title": page.title, "summary": page.summary, "kind": "page",
        })
    for relation in relations:
        version = versions.get(relation.source_version_id)
        source = sources.get(version.source_id) if version else None
        if not version or not source:
            continue
        out.append(_chain(source, version, relation_id=relation.id,
                          page_id=relation.source_page_id) | {
            "target_page_id": relation.target_page_id,
            "relation_type": relation.relation_type,
            "confidence": relation.confidence,
            "kind": "relation",
        })
    for source in source_rows:
        version = versions.get(source.active_version_id or "")
        if version:
            out.append(_chain(source, version) | {"kind": "source"})
    for version in direct_versions:
        source = sources.get(version.source_id)
        if source:
            out.append(_chain(source, version) | {"kind": "source_version"})
    return out[:limit]
