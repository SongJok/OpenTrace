"""会话级热知识缓存及 ``hot.md`` 渲染。"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class HotMemoryEntry:
    key: str
    title: str
    text: str
    score: float
    source_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    hits: int = 1
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class HotMemory:
    """有容量上限的最近知识缓存，可映射到 ConversationState 或 hot.md。"""

    def __init__(self, max_entries: int = 32) -> None:
        self.max_entries = max(1, max_entries)
        self._entries: OrderedDict[str, HotMemoryEntry] = OrderedDict()

    def remember(self, results: list[dict[str, Any]]) -> None:
        now = datetime.now(UTC).isoformat()
        for result in results:
            key = f"{result.get('source_type', 'knowledge')}:{result.get('id', result.get('title', ''))}"
            existing = self._entries.pop(key, None)
            entry = HotMemoryEntry(
                key=key,
                title=str(result.get("title") or "Knowledge"),
                text=str(result.get("text") or result.get("summary") or ""),
                score=max(
                    float(result.get("score", 0.0) or 0.0), existing.score if existing else 0.0
                ),
                source_type=str(result.get("source_type") or "knowledge_page"),
                payload=dict(result),
                hits=(existing.hits + 1 if existing else 1),
                updated_at=now,
            )
            self._entries[key] = entry
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def search(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", (query or "").lower())
        matches: list[tuple[float, HotMemoryEntry]] = []
        for entry in self._entries.values():
            haystack = f"{entry.title} {entry.text}".lower()
            hits = sum(1 for token in tokens if token in haystack)
            if hits:
                score = min(0.99, 0.82 + hits * 0.04 + min(entry.hits, 5) * 0.01)
                matches.append((score, entry))
        matches.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                **entry.payload,
                "score": score,
                "evidence_tier": "hot",
                "disclosure_stage": "hot",
            }
            for score, entry in matches[: max(1, top_k)]
        ]

    def entries(self) -> list[HotMemoryEntry]:
        return list(reversed(self._entries.values()))

    def render_markdown(self, *, workspace_id: str = "default") -> str:
        lines = [
            "---",
            "type: index",
            "title: 工作记忆",
            f"workspace_id: {workspace_id}",
            "auto_generated: true",
            "managed_by: opentrace",
            "---",
            "",
            "# 工作记忆",
            "",
        ]
        if not self._entries:
            lines.append("> 暂无活跃知识。完成查询或物化工作区后会自动更新。")
        else:
            lines.extend(["## 最近使用", ""])
            for entry in self.entries():
                lines.append(
                    f"- [[{entry.title}]] · {entry.source_type} · "
                    f"命中 {entry.hits} 次 · score={entry.score:.2f}"
                )
        return "\n".join(lines).rstrip() + "\n"
