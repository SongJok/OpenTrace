"""
ContextBuilder — 并行统一上下文构建

规则:
- 所有数据源并行检索（asyncio.gather），目标 < 300ms
- 每个来源带 metadata、confidence、source_type
- 合并后按 score 排序，截取 top_k
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from infra.metadata.unified_metadata import make_memory_metadata, make_web_metadata, UnifiedMetadata
from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ContextChunk:
    content: str
    source_type: str          # memory | document | knowledge | web | tool
    score: float = 1.0
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UnifiedContext:
    user_input: str
    chat_history: list[dict[str, str]] = field(default_factory=list)
    memory: list[ContextChunk] = field(default_factory=list)
    documents: list[ContextChunk] = field(default_factory=list)
    knowledge: list[ContextChunk] = field(default_factory=list)
    web: list[ContextChunk] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    build_latency_ms: int = 0

    def all_chunks(self, top_k: int = 10) -> list[ContextChunk]:
        all_c = self.memory + self.documents + self.knowledge + self.web
        return sorted(all_c, key=lambda c: c.score, reverse=True)[:top_k]

    def to_prompt_text(self, top_k: int = 8) -> str:
        parts: list[str] = []
        for chunk in self.all_chunks(top_k):
            label = chunk.source_type.upper()
            parts.append(f"[{label}](conf={chunk.confidence:.2f})\n{chunk.content[:600]}")
        if self.chat_history:
            recent = self.chat_history[-6:]
            hist = "\n".join(
                f"{h['role']}: {h['content'][:200]}" for h in recent
            )
            parts.append(f"[HISTORY]\n{hist}")
        return "\n\n---\n\n".join(parts)


class ContextBuilder:
    """
    并行构建统一上下文。

    用法:
        ctx = await ContextBuilder().build(query, session_id, history)
    """

    def __init__(self, memory_router=None, top_k: int = 6) -> None:
        self._memory_router = memory_router
        self.top_k = top_k

    def _normalize_metadata(
        self,
        source_type: str,
        raw: Optional[dict[str, Any]],
        user_id: str = "",
        defaults: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        data = dict(raw or {})
        if defaults:
            for k, v in defaults.items():
                data.setdefault(k, v)

        meta = UnifiedMetadata.from_dict(data) if data else UnifiedMetadata(
            type=source_type,
            owner=user_id,
            source="system",
        )
        if not meta.type:
            meta.type = source_type
        if user_id and not meta.owner:
            meta.owner = user_id
        return meta.to_dict()

    def _get_memory_router(self):
        if self._memory_router is None:
            from memory.memory_router.router import MemoryRouter
            self._memory_router = MemoryRouter()
        return self._memory_router

    def _build_database_summary(self, metadata: dict[str, Any]) -> dict[str, Any]:
        schema = metadata.get("data_source_schema")
        if not isinstance(schema, dict):
            return {}
        tables = schema.get("tables")
        if not isinstance(tables, list):
            return {}
        table_lines: list[str] = []
        for item in tables[:20]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("table_name") or item.get("name") or "").strip()
            if not name:
                continue
            columns = item.get("columns")
            col_names: list[str] = []
            if isinstance(columns, list):
                for col in columns[:8]:
                    if isinstance(col, dict):
                        col_name = str(col.get("column_name") or col.get("name") or "").strip()
                    else:
                        col_name = str(col).strip()
                    if col_name:
                        col_names.append(col_name)
            if col_names:
                table_lines.append(f"- {name}: {', '.join(col_names)}")
            else:
                table_lines.append(f"- {name}")
        summary_text = "\n".join(table_lines)
        if not summary_text:
            return {}
        return {
            "database_context": {
                "data_source_id": metadata.get("data_source_id"),
                "data_source_name": metadata.get("data_source_name"),
                "summary_text": summary_text,
            }
        }

    async def build(
        self,
        query: str,
        session_id: str = "",
        history: Optional[list[dict[str, str]]] = None,
        user_id: str = "",
        enable_web: bool = False,
        metadata: Optional[dict[str, Any]] = None,
    ) -> UnifiedContext:
        t0 = time.monotonic()
        history = history or []
        metadata = metadata or {}

        async def noop():
            return []

        # 4路完全并行
        results = await asyncio.gather(
            self._fetch_memory(query, user_id, session_id),
            self._fetch_documents(query, user_id),
            self._fetch_knowledge(query, user_id),
            self._fetch_web(query, user_id) if enable_web else noop(),
            return_exceptions=True,
        )

        memory_chunks   = results[0] if isinstance(results[0], list) else []
        doc_chunks      = results[1] if isinstance(results[1], list) else []
        know_chunks     = results[2] if isinstance(results[2], list) else []
        web_chunks      = results[3] if isinstance(results[3], list) else []

        latency = int((time.monotonic() - t0) * 1000)
        logger.info(
            "ContextBuilder.build",
            memory=len(memory_chunks),
            docs=len(doc_chunks),
            knowledge=len(know_chunks),
            web=len(web_chunks),
            latency_ms=latency,
        )

        return UnifiedContext(
            user_input=query,
            chat_history=history,
            memory=memory_chunks,
            documents=doc_chunks,
            knowledge=know_chunks,
            web=web_chunks,
            metadata={"session_id": session_id, "user_id": user_id, **metadata},
            build_latency_ms=latency,
        )

    async def _fetch_memory(self, query: str, user_id: str, session_id: str) -> list[ContextChunk]:
        try:
            router = self._get_memory_router()
            chunks = await router.retrieve(query=query, top_k=self.top_k)
            return [
                ContextChunk(
                    content=c.content,
                    source_type="memory",
                    score=c.score,
                    confidence=min(c.score, 1.0),
                    metadata=self._normalize_metadata(
                        "memory",
                        c.metadata,
                        user_id=user_id,
                        defaults=make_memory_metadata(owner=user_id, session_id=session_id).to_dict(),
                    ),
                )
                for c in chunks
            ]
        except Exception as exc:
            logger.debug("Memory fetch failed", error=str(exc))
            return []

    async def _fetch_documents(self, query: str, user_id: str) -> list[ContextChunk]:
        try:
            from plugins.document_plugin import DocumentPlugin
            result = await DocumentPlugin().search_chunks(query=query, user_id=user_id, top_k=self.top_k)
            return [
                ContextChunk(
                    content=c.content,
                    source_type=c.source_type,
                    score=c.score,
                    confidence=c.confidence,
                    metadata=self._normalize_metadata(
                        "document",
                        c.metadata,
                        user_id=user_id,
                        defaults={"source": "document_store"},
                    ),
                )
                for c in result
            ]
        except Exception as exc:
            logger.debug("Document fetch failed", error=str(exc))
            return []

    async def _fetch_knowledge(self, query: str, user_id: str) -> list[ContextChunk]:
        try:
            from memory.semantic_memory.semantic_memory import InMemorySemanticStore
            from model.embedding.base import get_embedder
            store = InMemorySemanticStore(embedder=get_embedder())
            chunks = await store.search(query, top_k=self.top_k)
            return [
                ContextChunk(
                    content=c.content,
                    source_type="knowledge",
                    score=c.score,
                    confidence=c.score,
                    metadata=self._normalize_metadata(
                        "knowledge",
                        c.metadata,
                        user_id=user_id,
                        defaults={"source": "knowledge_base"},
                    ),
                )
                for c in chunks
            ]
        except Exception as exc:
            logger.debug("Knowledge fetch failed", error=str(exc))
            return []

    async def _fetch_web(self, query: str, user_id: str) -> list[ContextChunk]:
        try:
            from plugins.web_plugin import WebPlugin
            chunks = await WebPlugin().search_chunks(query)
            return [
                ContextChunk(
                    content=c.content,
                    source_type=c.source_type,
                    score=c.score,
                    confidence=c.confidence,
                    metadata=self._normalize_metadata(
                        "web",
                        c.metadata,
                        user_id=user_id,
                        defaults=make_web_metadata(url=(c.metadata or {}).get("url", "")).to_dict(),
                    ),
                )
                for c in chunks
            ]
        except Exception as exc:
            logger.debug("Web fetch failed", error=str(exc))
            return []
 