"""语义缓存 — 基于嵌入的语义答案缓存。

通过嵌入相似度缓存查询-答案对；命中时（余弦相似度 ≥ 阈值）
直接返回缓存答案，无需走完整编排流水线。

使用项目的嵌入流水线进行向量化，使用 JSON 文件进行持久化
（轻量级，零基础设施）。生产部署可升级为 Redis/向量数据库。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache"
_DEFAULT_CACHE_FILE = "semantic_cache.json"
_DEFAULT_THRESHOLD = 0.92
_DEFAULT_MAX_ENTRIES = 10_000
_DEFAULT_TTL_SECONDS = 3_600


@dataclass
class CacheEntry:
    answer: str | None = None
    content: str | None = None
    hit_count: int = 0
    similarity: float = 0.0
    key: str = ""


class SemanticCache:
    """基于文件的语义答案缓存，使用嵌入相似度匹配。

    单进程使用下线程安全。多 worker 部署请升级为 Redis 存储。
    """

    def __init__(
        self,
        cache_dir: str | None = None,
        threshold: float | None = None,
        max_entries: int | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        self._cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
        self._cache_file = self._cache_dir / _DEFAULT_CACHE_FILE
        self._threshold = threshold if threshold is not None else _DEFAULT_THRESHOLD
        self._max_entries = max_entries if max_entries is not None else _DEFAULT_MAX_ENTRIES
        self._ttl = ttl_seconds if ttl_seconds is not None else _DEFAULT_TTL_SECONDS
        self._embedder = None
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_embedder(self):
        if self._embedder is None:
            try:
                from model.embedding.base import get_embedder
                self._embedder = get_embedder()
            except Exception:
                self._embedder = _FallbackEmbedder()
        return self._embedder

    def _load_entries(self) -> list[dict[str, Any]]:
        if not self._cache_file.exists():
            return []
        try:
            raw = self._cache_file.read_text(encoding="utf-8")
            return json.loads(raw)
        except (json.JSONDecodeError, OSError):
            return []

    def _save_entries(self, entries: list[dict[str, Any]]) -> None:
        self._cache_file.write_text(
            json.dumps(entries, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def _make_key(self, query: str, ctx_hash: str = "") -> str:
        raw = f"{query}:{ctx_hash}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def lookup(
        self, query: str, ctx_hash: str = ""
    ) -> CacheEntry | None:
        if not query or not query.strip():
            return None

        entries = self._load_entries()
        if not entries:
            return None

        now = time.time()

        # 淘汰过期条目
        valid_entries = [e for e in entries if now - e.get("stored_at", 0) < self._ttl]
        if len(valid_entries) < len(entries):
            # 按 LRU（最近使用）裁剪到最大条目数
            valid_entries.sort(key=lambda e: e.get("stored_at", 0), reverse=True)
            self._save_entries(valid_entries[:self._max_entries])

        if not valid_entries:
            return None

        # 计算查询嵌入
        embedder = self._get_embedder()
        try:
            query_vec = await embedder.embed_one(query)
        except Exception:
            return None

        if query_vec is None:
            return None

        # 按余弦相似度查找最佳匹配
        best_entry = None
        best_sim = 0.0
        for entry in valid_entries:
            stored_vec = entry.get("embedding")
            if not stored_vec:
                continue
            sim = _cosine_similarity(query_vec, stored_vec)
            if sim > best_sim:
                best_sim = sim
                best_entry = entry

        if best_entry and best_sim >= self._threshold:
            answer = best_entry.get("answer", "") or best_entry.get("content", "")
            try:
                from kernel.identity.system_identity import (
                    is_canonical_identity_response,
                    is_identity_user_query,
                )

                if is_canonical_identity_response(str(answer)) and not is_identity_user_query(
                    query
                ):
                    return None
            except Exception:
                pass
            best_entry["hit_count"] = best_entry.get("hit_count", 0) + 1
            best_entry["last_hit_at"] = now
            self._save_entries(valid_entries[:self._max_entries])
            return CacheEntry(
                answer=best_entry.get("answer", ""),
                content=best_entry.get("content", ""),
                hit_count=best_entry.get("hit_count", 0),
                similarity=round(best_sim, 4),
                key=best_entry.get("key", ""),
            )

        return None

    async def store(
        self, query: str, content: str, ctx_hash: str = ""
    ) -> None:
        if not query or not content:
            return
        try:
            from kernel.identity.system_identity import (
                is_canonical_identity_response,
                is_identity_user_query,
            )

            if is_canonical_identity_response(content) and not is_identity_user_query(query):
                return
        except Exception:
            pass

        embedder = self._get_embedder()
        try:
            query_vec = await embedder.embed_one(query)
        except Exception:
            return

        if query_vec is None:
            return

        entries = self._load_entries()
        now = time.time()

        # 移除过期条目
        entries = [e for e in entries if now - e.get("stored_at", 0) < self._ttl]

        # 去重：更新具有相同 key 的已有条目
        key = self._make_key(query, ctx_hash)
        for entry in entries:
            if entry.get("key") == key:
                entry["answer"] = content
                entry["content"] = content
                entry["embedding"] = query_vec
                entry["stored_at"] = now
                self._save_entries(entries[:self._max_entries])
                return

        entries.append({
            "key": key,
            "query": query[:500],
            "answer": content[:2000],
            "content": content[:2000],
            "embedding": query_vec,
            "stored_at": now,
            "hit_count": 0,
        })

        # LRU 淘汰
        entries.sort(key=lambda e: e.get("stored_at", 0), reverse=True)
        self._save_entries(entries[:self._max_entries])


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class _FallbackEmbedder:
    """降级嵌入器，使用 SHA256 哈希作为伪嵌入。

    在真实嵌入服务不可用时使用。
    哈希向量的余弦相似度不具备语义意义，
    但允许缓存模块在不崩溃的情况下运行。
    要实现真正的语义匹配，需要合适的嵌入模型。
    """

    async def embed_one(self, text: str) -> list[float]:
        import hashlib
        h = hashlib.sha256(text.encode()).digest()
        # 将前 32 字节转换为 32 个归一化为单位向量的浮点值
        vals = [float(b) / 255.0 for b in h[:32]]
        norm = sum(v * v for v in vals) ** 0.5
        if norm > 0:
            vals = [v / norm for v in vals]
        return vals
