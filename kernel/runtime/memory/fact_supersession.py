"""
事实取代引擎 — 管理事实的版本控制和替换。

当新事实到达并取代旧事实时（例如"CEO 现在是 B"取代"CEO 曾是 A"），
此引擎：
1. 将旧事实标记为已取代（不删除 — 保留谱系）
2. 通过 supersedes/superseded_by 链连接新 → 旧
3. 维护来源：为什么被取代、何时、由什么来源
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SupersessionRecord:
    """事实取代事件的记录。"""
    superseded_id: str = ""
    superseding_id: str = ""
    reason: str = ""
    source: str = ""  # 触发取代的来源（agent、human、system）
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


class FactSupersessionEngine:
    """管理事实的生命周期 — 创建、更新、取代。

    事实从不删除。它们被取代，维护完整的谱系
    用于审计和回放。
    """

    def __init__(self) -> None:
        self._records: list[SupersessionRecord] = []
        self._active_facts: dict[str, str] = {}  # entity_key → 最新 memory_id
        self._entity_roots: dict[str, str] = {}  # entity_key → 首个 memory_id
        self._lineage: dict[str, list[str]] = {}  # memory_id → [superseded_by_chain]

    def register_fact(self, entity_key: str, memory_id: str) -> None:
        """为实体注册新事实。"""
        if entity_key not in self._entity_roots:
            self._entity_roots[entity_key] = memory_id
        old_id = self._active_facts.get(entity_key)
        if old_id and old_id != memory_id:
            self.supersede(
                entity_key=entity_key,
                old_memory_id=old_id,
                new_memory_id=memory_id,
                reason="newer fact registered",
            )
        self._active_facts[entity_key] = memory_id

    def supersede(
        self,
        entity_key: str,
        old_memory_id: str,
        new_memory_id: str,
        reason: str = "",
        source: str = "system",
    ) -> SupersessionRecord:
        """用新事实取代旧事实。

        返回取代记录用于审计追踪。
        """
        record = SupersessionRecord(
            superseded_id=old_memory_id,
            superseding_id=new_memory_id,
            reason=reason,
            source=source,
        )
        self._records.append(record)

        # 更新谱系
        self._lineage.setdefault(old_memory_id, []).append(new_memory_id)
        if old_memory_id in self._lineage:
            # 继承链
            self._lineage[new_memory_id] = list(self._lineage[old_memory_id])

        # 更新活跃事实
        if self._active_facts.get(entity_key) == old_memory_id:
            self._active_facts[entity_key] = new_memory_id

        return record

    def is_superseded(self, memory_id: str) -> bool:
        """检查记忆是否已被取代。"""
        return any(
            r.superseded_id == memory_id for r in self._records
        )

    def get_superseding(self, memory_id: str) -> str | None:
        """获取取代此记忆的 memory_id。"""
        for r in self._records:
            if r.superseded_id == memory_id:
                return r.superseding_id
        return None

    def get_lineage(self, memory_id: str) -> list[str]:
        """获取记忆的完整谱系链。"""
        chain: list[str] = [memory_id]
        current = memory_id
        while True:
            next_id = self.get_superseding(current)
            if next_id is None or next_id in chain:
                break
            chain.append(next_id)
            current = next_id
        return chain

    def get_latest(self, entity_key: str) -> str | None:
        """获取实体的最新（未被取代的）memory_id。"""
        return self._active_facts.get(entity_key)

    def get_history(self, entity_key: str) -> list[SupersessionRecord]:
        """获取实体的所有取代记录。"""
        root_id = self._entity_roots.get(entity_key)
        if root_id is None:
            return []
        lineage_ids = set(self.get_lineage(root_id))
        return [
            r for r in self._records
            if r.superseded_id in lineage_ids or r.superseding_id in lineage_ids
        ]

    def summary(self) -> dict[str, Any]:
        return {
            "total_supersessions": len(self._records),
            "active_fact_count": len(self._active_facts),
            "entity_count": len(self._active_facts),
        }
