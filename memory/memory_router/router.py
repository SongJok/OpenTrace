"""
Memory Router — federated retrieval + async write-back.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from infra.config.settings import settings
from infra.metadata.unified_metadata import make_memory_metadata
from infra.observability.logger import get_logger
from infra.observability.metrics import MEMORY_HITS
from infra.observability.tracer import get_tracer
from memory.semantic_memory.semantic_memory import InMemorySemanticStore
from model.embedding.base import BaseEmbedder, get_embedder
from model.reranker.base import BaseReranker, RankedResult, get_reranker

logger = get_logger(__name__)
tracer = get_tracer(__name__)


@dataclass
class MemoryChunk:
    content: str
    score: float
    source: str  # vector | episodic | keyword | graph
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Module-level singleton ──────────────────────────────────────────────
# EvolutionMemoryRouter is the production default because it adds
# reinforcement, skill retrieval, and evolution on top of base retrieval.
# Both CognitiveKernel (read) and MemoryEventSubscriber (write) share this
# single instance so semantic store data is visible to both paths.
_global_memory_router: Optional["MemoryRouter"] = None


def get_memory_router() -> "MemoryRouter":
    """Return the process-wide singleton MemoryRouter (EvolutionMemoryRouter by default)."""
    global _global_memory_router
    if _global_memory_router is None:
        from memory.evolution.router import EvolutionMemoryRouter
        _global_memory_router = EvolutionMemoryRouter()
    return _global_memory_router


class MemoryRouter:
    """
    Federated memory:
      retrieve() — semantic + episodic + keyword + graph stub -> rerank
      store()    — async write-back after each response
    """

    def __init__(
        self,
        embedder: Optional[BaseEmbedder] = None,
        reranker: Optional[BaseReranker] = None,
        semantic_store: Optional[InMemorySemanticStore] = None,
    ) -> None:
        self.embedder = embedder or get_embedder()
        self.reranker = reranker or get_reranker()
        self.semantic_store = semantic_store or InMemorySemanticStore(embedder=self.embedder)

    # ------------------------------------------------------------------
    # Retrieve
    # ------------------------------------------------------------------
    async def retrieve(
        self,
        query: str,
        episodic_chunks: Optional[list[str]] = None,
        keyword_chunks: Optional[list[str]] = None,
        top_k: int = 8,
    ) -> list[MemoryChunk]:
        with tracer.start_as_current_span("memory_router.retrieve") as span:
            span.set_attribute("query.length", len(query))

            all_texts: list[str] = []
            source_map: dict[int, str] = {}

            # 1. Semantic vector search
            try:
                for chunk in await self.semantic_store.search(query, top_k=top_k):
                    source_map[len(all_texts)] = "vector"
                    all_texts.append(chunk.content)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Semantic search error", error=str(exc))

            # 2. Graph search (stub — replace with neo4j / networkx queries)
            try:
                for chunk in await self._graph_search(query):
                    source_map[len(all_texts)] = "graph"
                    all_texts.append(chunk)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Graph search error", error=str(exc))

            # 3. Episodic
            for chunk in (episodic_chunks or []):
                source_map[len(all_texts)] = "episodic"
                all_texts.append(chunk)

            # 4. Keyword
            for chunk in (keyword_chunks or []):
                source_map[len(all_texts)] = "keyword"
                all_texts.append(chunk)

            if not all_texts:
                return []

            ranked: list[RankedResult] = await self.reranker.rerank(
                query=query, candidates=all_texts, top_k=top_k,
            )

            results: list[MemoryChunk] = []
            for r in ranked:
                source = source_map.get(r.index, "unknown")
                MEMORY_HITS.labels(store_type=source).inc()
                meta = make_memory_metadata(owner="", session_id="").to_dict()
                meta.update({"source": source, "confidence": float(r.score)})
                results.append(
                    MemoryChunk(
                        content=r.text,
                        score=r.score,
                        source=source,
                        metadata=meta,
                    )
                )

            # ── Feature ③: Value scoring with recency + feedback ──
            if bool(getattr(settings, "kernel_memory_value_scoring_enabled", True)):
                try:
                    from memory.value_scorer import get_value_scorer
                    scorer = get_value_scorer()
                    # Use a default current turn (memory router doesn't track turns directly)
                    # Feedback scores would come from Redis, use 0.0 as default
                    for chunk in results:
                        base = chunk.score
                        components = scorer.compute_score(
                            base_score=base,
                            turn_number=0,   # Not tracked here, neutral recency
                            current_turn=0,
                            feedback_score=0.0,  # Will be enriched from Redis in EvolutionMemoryRouter
                        )
                        chunk.score = components.final_score
                        chunk.metadata["value_components"] = {
                            "base": components.base_score,
                            "recency": components.recency_score,
                            "feedback": components.feedback_score,
                            "final": components.final_score,
                        }
                    # Re-sort by final score
                    results.sort(key=lambda c: c.score, reverse=True)
                except Exception:
                    pass  # Degrade gracefully if scorer unavailable
            # ── End value scoring ────────────────────────────

            span.set_attribute("memory.hits", len(results))
            return results

    # ------------------------------------------------------------------
    # Store (write-back called async after each response)
    # ------------------------------------------------------------------
    async def store(
        self,
        session_id: str,
        query: str,
        answer: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Persist query+answer pair into the semantic store for future retrieval."""
        try:
            chunk_id = str(uuid.uuid4())
            content = f"Q: {query}\nA: {answer}"
            meta_in = metadata or {}
            owner = str(meta_in.get("user_id") or meta_in.get("owner") or "")
            base_meta = make_memory_metadata(owner=owner, session_id=session_id).to_dict()
            base_meta.update(meta_in)
            await self.semantic_store.add(chunk_id, content, base_meta)
            logger.debug("Memory stored", session=session_id, chunk_id=chunk_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Memory store failed", error=str(exc))

    # ------------------------------------------------------------------
    # Convenience helper
    # ------------------------------------------------------------------
    async def add_to_semantic(
        self,
        chunk_id: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        await self.semantic_store.add(chunk_id, content, metadata)
        logger.debug("Chunk indexed", chunk_id=chunk_id)

    # ------------------------------------------------------------------
    # Graph search stub
    # ------------------------------------------------------------------
    async def _graph_search(self, query: str) -> list[str]:
        """
        Stub for knowledge-graph traversal.
        Replace with Neo4j / networkx / kuzu queries in production.
        """
        return []
