"""
Semantic Memory — vector-based long-term knowledge store.
Uses pgvector when available, falls back to in-memory cosine similarity.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from infra.observability.logger import get_logger
from infra.observability.metrics import MEMORY_HITS
from model.embedding.base import BaseEmbedder, get_embedder

logger = get_logger(__name__)


@dataclass
class SemanticChunk:
    chunk_id: str
    content: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class InMemorySemanticStore:
    """
    Simple in-memory semantic store using cosine similarity.
    Replace with pgvector queries in production.
    """

    def __init__(self, embedder: Optional[BaseEmbedder] = None) -> None:
        self.embedder = embedder or get_embedder()
        self._chunks: list[SemanticChunk] = []

    async def add(
        self,
        chunk_id: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        vec = await self.embedder.embed_one(content)
        self._chunks.append(
            SemanticChunk(
                chunk_id=chunk_id,
                content=content,
                embedding=vec,
                metadata=metadata or {},
            )
        )

    async def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[SemanticChunk]:
        import numpy as np

        if not self._chunks:
            return []

        q_vec = np.array(await self.embedder.embed_one(query), dtype=np.float32)
        scores: list[tuple[float, SemanticChunk]] = []
        for chunk in self._chunks:
            c_vec = np.array(chunk.embedding, dtype=np.float32)
            score = float(np.dot(q_vec, c_vec))
            scores.append((score, chunk))

        scores.sort(key=lambda x: x[0], reverse=True)
        results = [c for _, c in scores[:top_k]]
        MEMORY_HITS.labels(store_type="vector").inc(len(results))
        return results
