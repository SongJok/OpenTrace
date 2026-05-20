"""Semantic History Retriever — session-scoped vector index of conversation turns.
Embeds each assistant response and retrieves top-K related turns via cosine similarity,
so that deictic references (e.g. "那华南呢?") resolve to the correct prior context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.config.settings import settings
from infra.observability.logger import get_logger
from memory.semantic_memory.semantic_memory import InMemorySemanticStore
from model.embedding.base import BaseEmbedder, get_embedder

logger = get_logger(__name__)

_SESSION_STORES: dict[str, InMemorySemanticStore] = {}


@dataclass
class HistoryTurn:
    turn_number: int = 0
    query: str = ""
    answer: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class SemanticHistoryRetriever:
    """Session-scoped semantic index over conversation turns.

    Each turn (query + answer) is embedded and stored in the session's vector index.
    On retrieval, the current query is embedded and the top-K most similar past turns
    are returned — enabling the model to recall relevant prior discussion without
    needing every turn in the prompt.
    """

    def __init__(self, embedder: BaseEmbedder | None = None) -> None:
        self.embedder = embedder or get_embedder()
        self._enabled = bool(getattr(settings, "kernel_semantic_history_enabled", True))
        self._top_k = int(getattr(settings, "kernel_semantic_history_top_k", 3))
        self._min_score = float(getattr(settings, "kernel_semantic_history_min_score", 0.25))

    def _get_store(self, session_id: str) -> InMemorySemanticStore:
        if session_id not in _SESSION_STORES:
            _SESSION_STORES[session_id] = InMemorySemanticStore(
                embedder=self.embedder
            )
        return _SESSION_STORES[session_id]

    async def index_turn(
        self,
        session_id: str,
        turn_number: int,
        query: str,
        answer: str,
    ) -> None:
        if not self._enabled or not session_id or not answer:
            return
        try:
            store = self._get_store(session_id)
            chunk_id = f"turn:{turn_number}"
            content = f"Q: {query.strip()}\nA: {answer.strip()}"
            await store.add(
                chunk_id,
                content,
                metadata={
                    "turn_number": turn_number,
                    "query": query.strip(),
                    "type": "conversation_turn",
                },
            )
        except Exception:
            logger.debug("SemanticHistoryRetriever index_turn failed", exc_info=True)

    async def retrieve(
        self,
        query: str,
        session_id: str,
        top_k: int | None = None,
    ) -> list[HistoryTurn]:
        if not self._enabled or not session_id or session_id not in _SESSION_STORES:
            return []
        try:
            store = _SESSION_STORES[session_id]
            k = top_k if top_k else self._top_k
            results = await store.search(query, top_k=k)
            turns: list[HistoryTurn] = []
            for chunk in results:
                if chunk.score < self._min_score:
                    continue
                meta = chunk.metadata or {}
                if "\nA: " in chunk.content:
                    answer = chunk.content.split("\nA: ", 1)[-1]
                else:
                    answer = chunk.content
                turns.append(
                    HistoryTurn(
                        turn_number=int(meta.get("turn_number", 0)),
                        query=str(meta.get("query", "")),
                        answer=answer,
                        score=chunk.score,
                        metadata=meta,
                    )
                )
            return turns
        except Exception:
            logger.debug("SemanticHistoryRetriever retrieve failed", exc_info=True)
            return []

    async def clear_session(self, session_id: str) -> None:
        _SESSION_STORES.pop(session_id, None)

    @classmethod
    async def clear_all(cls) -> None:
        _SESSION_STORES.clear()
