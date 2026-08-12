"""工作区知识网络物化与读取模型。"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    KnowledgeClaim,
    KnowledgePage,
    KnowledgeRelation,
    KnowledgeSource,
    KnowledgeSourceVersion,
)
from knowledge.compiler import stable_id


def _entity_key(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (value or "").lower())


async def link_workspace_pages(
    db: AsyncSession,
    *,
    owner_id: str,
    tenant_id: str,
    workspace_id: str,
    max_pages: int = 400,
) -> dict[str, int]:
    """Create conservative, traceable cross-document entity/reference edges."""
    stmt = (
        select(KnowledgePage, KnowledgeSource)
        .join(KnowledgeSourceVersion, KnowledgePage.source_version_id == KnowledgeSourceVersion.id)
        .join(KnowledgeSource, KnowledgeSourceVersion.source_id == KnowledgeSource.id)
        .where(
            KnowledgePage.owner_id == owner_id,
            KnowledgePage.tenant_id == tenant_id,
            KnowledgePage.workspace_id == workspace_id,
            KnowledgePage.status == "published",
            KnowledgeSource.status == "published",
            KnowledgeSource.active_version_id == KnowledgeSourceVersion.id,
        )
        .order_by(KnowledgePage.updated_at.desc())
        .limit(max(1, min(max_pages, 1000)))
    )
    rows = (await db.execute(stmt)).all()
    existing = set(
        (
            await db.execute(
                select(
                    KnowledgeRelation.source_page_id,
                    KnowledgeRelation.target_page_id,
                    KnowledgeRelation.relation_type,
                ).where(
                    KnowledgeRelation.owner_id == owner_id,
                    KnowledgeRelation.tenant_id == tenant_id,
                    KnowledgeRelation.workspace_id == workspace_id,
                )
            )
        ).all()
    )
    created = 0
    for source_page, source in rows:
        source_key = _entity_key(source_page.title)
        if not source_key or source_page.page_type == "overview":
            continue
        source_text = _entity_key(source_page.content)
        for target_page, target_source in rows:
            if source.id == target_source.id or source_page.id == target_page.id:
                continue
            target_key = _entity_key(target_page.title)
            if len(target_key) < 2 or target_page.page_type == "overview":
                continue
            relation_type = (
                "same_as"
                if source_key == target_key
                else "references" if target_key in source_text else ""
            )
            key = (source_page.id, target_page.id, relation_type)
            if not relation_type or key in existing:
                continue
            db.add(
                KnowledgeRelation(
                    id=stable_id("workspace-relation", ":".join(key)),
                    source_version_id=source_page.source_version_id,
                    owner_id=owner_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    source_page_id=source_page.id,
                    target_page_id=target_page.id,
                    relation_type=relation_type,
                    authority="contextual",
                    confidence=0.82 if relation_type == "same_as" else 0.76,
                    status="published",
                    relation_metadata={
                        "generated_by": "workspace_graph_linker_v1",
                        "source_document_id": source.document_id,
                        "target_document_id": target_source.document_id,
                    },
                )
            )
            existing.add(key)
            created += 1
            if created >= 2000:
                break
        if created >= 2000:
            break
    await db.flush()
    return {"pages": len(rows), "relations_created": created}


async def build_knowledge_graph(
    db: AsyncSession,
    *,
    owner_id: str,
    tenant_id: str,
    workspace_id: str,
    network: str = "entity",
) -> dict[str, Any]:
    """Return entity, dependency, or provenance networks for the UI."""
    network = network if network in {"entity", "dependency", "provenance"} else "entity"
    page_stmt = (
        select(KnowledgePage, KnowledgeSource)
        .join(KnowledgeSourceVersion, KnowledgePage.source_version_id == KnowledgeSourceVersion.id)
        .join(KnowledgeSource, KnowledgeSourceVersion.source_id == KnowledgeSource.id)
        .where(
            KnowledgePage.owner_id == owner_id,
            KnowledgePage.tenant_id == tenant_id,
            KnowledgePage.workspace_id == workspace_id,
            KnowledgePage.status == "published",
            KnowledgeSource.status == "published",
            KnowledgeSource.active_version_id == KnowledgeSourceVersion.id,
        )
    )
    page_rows = (await db.execute(page_stmt.limit(800))).all()
    page_ids = {page.id for page, _ in page_rows}

    if network == "provenance":
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        for page, source in page_rows:
            if source.id not in seen_sources:
                seen_sources.add(source.id)
                nodes.append(
                    {
                        "id": source.id,
                        "label": source.title,
                        "type": "source",
                        "document_id": source.document_id,
                    }
                )
            nodes.append(
                {"id": page.id, "label": page.title, "type": "page", "page_type": page.page_type}
            )
            edges.append(
                {
                    "id": f"{source.id}:{page.id}",
                    "source": source.id,
                    "target": page.id,
                    "type": "compiled_to",
                }
            )
        claims = (
            (
                await db.execute(
                    select(KnowledgeClaim)
                    .where(
                        KnowledgeClaim.page_id.in_(page_ids),
                        KnowledgeClaim.status == "published",
                    )
                    .limit(1200)
                )
            )
            .scalars()
            .all()
            if page_ids
            else []
        )
        for claim in claims:
            nodes.append({"id": claim.id, "label": claim.text[:72], "type": "claim"})
            edges.append(
                {
                    "id": f"{claim.page_id}:{claim.id}",
                    "source": claim.page_id,
                    "target": claim.id,
                    "type": "asserts",
                }
            )
        return {"network": network, "nodes": nodes, "edges": edges}

    relation_rows = (
        (
            await db.execute(
                select(KnowledgeRelation)
                .where(
                    KnowledgeRelation.source_page_id.in_(page_ids),
                    KnowledgeRelation.target_page_id.in_(page_ids),
                    KnowledgeRelation.status == "published",
                )
                .limit(2500)
            )
        )
        .scalars()
        .all()
        if page_ids
        else []
    )
    dependency_types = {"contains", "part_of", "references", "depends_on", "required_by"}
    if network == "dependency":
        relation_rows = [row for row in relation_rows if row.relation_type in dependency_types]
    nodes = [
        {
            "id": page.id,
            "label": page.title,
            "type": "entity" if network == "entity" else page.page_type,
            "page_type": page.page_type,
            "source_id": source.id,
            "document_id": source.document_id,
            "confidence": page.confidence,
        }
        for page, source in page_rows
        if network != "entity" or page.page_type != "overview"
    ]
    visible_ids = {node["id"] for node in nodes}
    edges = [
        {
            "id": row.id,
            "source": row.source_page_id,
            "target": row.target_page_id,
            "type": row.relation_type,
            "confidence": row.confidence,
        }
        for row in relation_rows
        if row.source_page_id in visible_ids and row.target_page_id in visible_ids
    ]
    return {"network": network, "nodes": nodes, "edges": edges}
