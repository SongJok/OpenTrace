from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from sqlalchemy import select

from infra.storage.database import AsyncSessionLocal
from infra.storage.models import UserMemory
from model.embedding.base import get_embedder


@dataclass
class _SemanticNode:
    memory: UserMemory
    embedding: np.ndarray


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 1e-8:
        return 0.0
    return float(np.dot(a, b) / denom)


def _cluster_by_similarity(nodes: list[_SemanticNode], threshold: float) -> list[list[_SemanticNode]]:
    clusters: list[list[_SemanticNode]] = []
    for node in nodes:
        placed = False
        for c in clusters:
            # simple single-link clustering
            if any(_cosine(node.embedding, x.embedding) >= threshold for x in c):
                c.append(node)
                placed = True
                break
        if not placed:
            clusters.append([node])
    return clusters


def _dedup_keep_order(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen = set()
    for v in values:
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


async def evolve_once(
    similarity_threshold: float = 0.88,
    min_access_to_keep: int = 1,
    dry_run: bool = True,
) -> dict[str, int]:
    merged = 0
    deleted = 0
    procedural_created = 0

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(UserMemory).where(UserMemory.enabled.is_(True)))
        memories = list(r.scalars().all())

        # 1) merge similar semantic memories with embedding similarity
        semantic_memories = [m for m in memories if m.memory_type == "semantic" and (m.content or "").strip()]
        if semantic_memories:
            embedder = get_embedder()
            vectors = await embedder.embed([m.content for m in semantic_memories])
            by_user_nodes: dict[str, list[_SemanticNode]] = defaultdict(list)
            for m, v in zip(semantic_memories, vectors):
                by_user_nodes[m.user_id].append(_SemanticNode(memory=m, embedding=np.array(v, dtype=np.float32)))

            for _, nodes in by_user_nodes.items():
                clusters = _cluster_by_similarity(nodes, threshold=similarity_threshold)
                for c in clusters:
                    if len(c) < 2:
                        continue
                    c_sorted = sorted(c, key=lambda x: (x.memory.pinned, x.memory.updated_at), reverse=True)
                    keeper = c_sorted[0].memory
                    keeper.content = "\n".join(_dedup_keep_order(x.memory.content for x in c_sorted))
                    keeper.metadata_json = json.dumps(
                        {
                            "evolved": True,
                            "source": "embedding_merge",
                            "cluster_size": len(c_sorted),
                            "similarity_threshold": similarity_threshold,
                        },
                        ensure_ascii=False,
                    )
                    for x in c_sorted[1:]:
                        if not dry_run:
                            await db.delete(x.memory)
                        deleted += 1
                    merged += 1

        # 2) delete low-access old memories (simple policy)
        for m in memories:
            if (m.access_count or 0) < min_access_to_keep and not m.pinned and m.memory_type in {"episodic", "semantic"}:
                if not dry_run:
                    await db.delete(m)
                deleted += 1

        # 3) derive procedural templates from episodic high-signal patterns
        by_user = defaultdict(list)
        for m in memories:
            if m.memory_type == "episodic" and m.content:
                by_user[m.user_id].append(m.content)
        for user_id, items in by_user.items():
            if len(items) < 3:
                continue
            template = UserMemory(
                user_id=user_id,
                memory_type="procedural",
                kind="workflow",
                title="Auto-derived workflow template",
                content="\n".join(items[:3]),
                tags_json=json.dumps(["auto", "derived"], ensure_ascii=False),
                metadata_json=json.dumps({"source": "memory_evolve"}, ensure_ascii=False),
                enabled=True,
                pinned=False,
            )
            if not dry_run:
                db.add(template)
            procedural_created += 1

        if not dry_run:
            await db.commit()

    return {"merged": merged, "deleted": deleted, "procedural_created": procedural_created}


if __name__ == "__main__":
    result = asyncio.run(evolve_once(dry_run=True))
    print(json.dumps(result, ensure_ascii=False))
