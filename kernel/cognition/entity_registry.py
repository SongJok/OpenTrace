"""企业实体注册表（轻量原型）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EntityRecord:
    canonical_name: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)
    mappings: dict[str, Any] = field(default_factory=dict)


class EntityRegistry:
    def __init__(self) -> None:
        self._by_alias: dict[str, EntityRecord] = {}
        self._records: list[EntityRecord] = []
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        self.register(
            EntityRecord(
                canonical_name="华东",
                entity_type="region",
                aliases=["华东区", "east china", "east"],
                mappings={"sql": {"region": "华东"}},
            )
        )
        self.register(
            EntityRecord(
                canonical_name="上季度",
                entity_type="time_range",
                aliases=["上一季度", "q-1"],
                mappings={"time_expr": "last_quarter"},
            )
        )

    def register(self, record: EntityRecord) -> None:
        self._records.append(record)
        keys = {record.canonical_name, *record.aliases}
        for k in keys:
            self._by_alias[k.strip().lower()] = record

    def lookup(self, term: str) -> EntityRecord | None:
        return self._by_alias.get((term or "").strip().lower())

    def all(self) -> list[EntityRecord]:
        return list(self._records)
