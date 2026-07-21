from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import UserMemory, UserMemoryRelation


def _terms(text: str) -> set[str]:
    lowered = text.lower()
    values = set(re.findall(r"[a-z0-9_]{2,}", lowered))
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(run) == 1:
            values.add(run)
        else:
            values.update(run[index : index + 2] for index in range(len(run) - 1))
    return values


async def link_memory_graph(
    db: AsyncSession,
    *,
    memory: UserMemory,
    evidence_response_id: str | None = None,
    max_edges: int = 8,
) -> list[UserMemoryRelation]:
    """为新记忆建立同范围的一跳关系，所有边都保留可审计来源。"""

    if not memory.enabled or memory.status != "active":
        return []

    candidates = list(
        (
            await db.execute(
                select(UserMemory)
                .where(
                    UserMemory.id != memory.id,
                    UserMemory.user_id == memory.user_id,
                    UserMemory.tenant_id == memory.tenant_id,
                    UserMemory.workspace_id == memory.workspace_id,
                    UserMemory.enabled.is_(True),
                    UserMemory.status == "active",
                    UserMemory.scope_type == memory.scope_type,
                    UserMemory.scope_id == memory.scope_id,
                )
                .order_by(UserMemory.updated_at.desc())
                .limit(120)
            )
        )
        .scalars()
        .all()
    )
    source_terms = _terms(" ".join((memory.memory_key or "", memory.content or "")))
    scored: list[tuple[float, str, UserMemory]] = []
    for candidate in candidates:
        relation = "related_to"
        if memory.supersedes_id == candidate.id:
            relation = "supersedes"
            score = 1.0
        else:
            target_terms = _terms(" ".join((candidate.memory_key or "", candidate.content or "")))
            overlap = len(source_terms & target_terms) / max(1, len(source_terms | target_terms))
            same_namespace = bool(
                memory.memory_key
                and candidate.memory_key
                and memory.memory_key.split(".", 1)[0] == candidate.memory_key.split(".", 1)[0]
            )
            same_kind = memory.kind == candidate.kind
            score = overlap + (0.35 if same_namespace else 0.0) + (0.08 if same_kind else 0.0)
            if score < 0.16:
                continue
            relation = "same_topic" if same_namespace else "supports"
        scored.append((min(1.0, score), relation, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)

    created: list[UserMemoryRelation] = []
    for score, relation, candidate in scored[: max(1, max_edges)]:
        source_id, target_id = memory.id, candidate.id
        if relation != "supersedes" and source_id > target_id:
            source_id, target_id = target_id, source_id
        existing = await db.scalar(
            select(UserMemoryRelation).where(
                UserMemoryRelation.user_id == memory.user_id,
                UserMemoryRelation.tenant_id == memory.tenant_id,
                UserMemoryRelation.workspace_id == memory.workspace_id,
                UserMemoryRelation.source_memory_id == source_id,
                UserMemoryRelation.target_memory_id == target_id,
                UserMemoryRelation.relation_type == relation,
            )
        )
        if existing:
            existing.weight = max(float(existing.weight or 0.0), score)
            existing.evidence_response_id = evidence_response_id or existing.evidence_response_id
            created.append(existing)
            continue
        edge = UserMemoryRelation(
            id=str(uuid.uuid4()),
            user_id=memory.user_id,
            tenant_id=memory.tenant_id,
            workspace_id=memory.workspace_id,
            source_memory_id=source_id,
            target_memory_id=target_id,
            relation_type=relation,
            weight=score,
            evidence_response_id=evidence_response_id,
            relation_metadata={"source": "automatic_topic_linker"},
        )
        db.add(edge)
        created.append(edge)
    return created


async def rebuild_memory_graph_links(
    db: AsyncSession,
    *,
    memory: UserMemory,
    evidence_response_id: str | None = None,
) -> list[UserMemoryRelation]:
    await db.execute(
        delete(UserMemoryRelation).where(
            or_(
                UserMemoryRelation.source_memory_id == memory.id,
                UserMemoryRelation.target_memory_id == memory.id,
            )
        )
    )
    return await link_memory_graph(
        db,
        memory=memory,
        evidence_response_id=evidence_response_id,
    )


async def memory_graph_boosts(
    db: AsyncSession,
    *,
    memory_ids: list[str],
    user_id: str,
    tenant_id: str,
    workspace_id: str,
) -> tuple[dict[str, float], list[UserMemoryRelation]]:
    if not memory_ids:
        return {}, []
    edges = list(
        (
            await db.execute(
                select(UserMemoryRelation).where(
                    UserMemoryRelation.user_id == user_id,
                    UserMemoryRelation.tenant_id == tenant_id,
                    UserMemoryRelation.workspace_id == workspace_id,
                    or_(
                        UserMemoryRelation.source_memory_id.in_(memory_ids),
                        UserMemoryRelation.target_memory_id.in_(memory_ids),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    boosts: dict[str, float] = {}
    anchors = set(memory_ids)
    for edge in edges:
        if edge.source_memory_id in anchors:
            boosts[edge.target_memory_id] = max(
                boosts.get(edge.target_memory_id, 0.0), float(edge.weight or 0.0)
            )
        if edge.target_memory_id in anchors:
            boosts[edge.source_memory_id] = max(
                boosts.get(edge.source_memory_id, 0.0), float(edge.weight or 0.0)
            )
    return boosts, edges


async def scoped_memory_graph(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
) -> dict[str, Any]:
    memories = list(
        (
            await db.execute(
                select(UserMemory).where(
                    UserMemory.user_id == user_id,
                    UserMemory.tenant_id == tenant_id,
                    UserMemory.workspace_id == workspace_id,
                    UserMemory.enabled.is_(True),
                    UserMemory.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    ids = {memory.id for memory in memories}
    edges = list(
        (
            await db.execute(
                select(UserMemoryRelation).where(
                    UserMemoryRelation.user_id == user_id,
                    UserMemoryRelation.tenant_id == tenant_id,
                    UserMemoryRelation.workspace_id == workspace_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        "nodes": [
            {
                "id": memory.id,
                "label": memory.title or memory.content[:80],
                "kind": memory.kind,
                "scope_type": memory.scope_type,
                "salience": memory.salience,
            }
            for memory in memories
        ],
        "edges": [
            {
                "id": edge.id,
                "source": edge.source_memory_id,
                "target": edge.target_memory_id,
                "relation": edge.relation_type,
                "weight": edge.weight,
            }
            for edge in edges
            if edge.source_memory_id in ids and edge.target_memory_id in ids
        ],
    }
