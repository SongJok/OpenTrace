"""世界模型：做语义接地与消歧。"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

from infra.config.settings import settings
from kernel.cognition.entity_registry import EntityRecord, EntityRegistry
from kernel.cognition.types import GroundedEntity


class WorldModel:
    def __init__(self) -> None:
        self.entity_registry = EntityRegistry()
        self._load_external_lexicon()

    def _load_external_lexicon(self) -> None:
        raw = str(getattr(settings, "cognition_lexicon_json", "") or "").strip()
        if not raw:
            return
        try:
            data = json.loads(raw)
            if not isinstance(data, list):
                return
            for item in data:
                if not isinstance(item, dict):
                    continue
                canonical_name = str(item.get("canonical_name") or "").strip()
                entity_type = str(item.get("entity_type") or "").strip()
                if not canonical_name or not entity_type:
                    continue
                aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
                mappings = item.get("mappings") if isinstance(item.get("mappings"), dict) else {}
                self.entity_registry.register(
                    EntityRecord(
                        canonical_name=canonical_name,
                        entity_type=entity_type,
                        aliases=[str(x) for x in aliases if str(x).strip()],
                        mappings=mappings,
                    )
                )
        except Exception:
            return

    def ground(self, ambiguous_term: str) -> GroundedEntity:
        rec = self.entity_registry.lookup(ambiguous_term)
        if rec:
            return GroundedEntity(
                original_term=ambiguous_term,
                entity_type=rec.entity_type,
                canonical_name=rec.canonical_name,
                mappings=rec.mappings,
                confidence=0.92,
                alternatives=rec.aliases,
            )

        time_map = self._ground_time_phrase(ambiguous_term)
        if time_map:
            return GroundedEntity(
                original_term=ambiguous_term,
                entity_type="time_range",
                canonical_name=time_map["canonical_name"],
                mappings=time_map["mappings"],
                confidence=0.88,
                alternatives=time_map.get("alternatives", []),
            )

        return GroundedEntity(
            original_term=ambiguous_term,
            entity_type="unknown",
            canonical_name=ambiguous_term,
            mappings={},
            confidence=0.3,
            alternatives=[],
        )

    def ground_query(self, query: str) -> list[GroundedEntity]:
        q = (query or "").strip()
        if not q:
            return []

        matched: list[GroundedEntity] = []
        best_by_sig: dict[tuple[str, str], GroundedEntity] = {}

        # 1) 基于注册表全量别名扫描
        for rec in self.entity_registry.all():
            keys = [rec.canonical_name, *rec.aliases]
            for k in keys:
                key = (k or "").strip()
                if not key:
                    continue
                if key.lower() in q.lower():
                    g = GroundedEntity(
                        original_term=key,
                        entity_type=rec.entity_type,
                        canonical_name=rec.canonical_name,
                        mappings=rec.mappings,
                        confidence=0.92,
                        alternatives=rec.aliases,
                    )
                    sig = (g.entity_type, g.canonical_name)
                    old = best_by_sig.get(sig)
                    if old is None or g.confidence > old.confidence:
                        best_by_sig[sig] = g

        # 2) 时间语义补充（中英文）
        for phrase in [
            "今天", "昨日", "昨天", "本周", "上周", "本月", "上月", "本季度", "上季度", "今年", "去年",
            "today", "yesterday", "this week", "last week", "this month", "last month", "this quarter", "last quarter", "this year", "last year",
        ]:
            if phrase.lower() in q.lower():
                g = self.ground(phrase)
                sig = (g.entity_type, g.canonical_name)
                if g.entity_type != "unknown":
                    old = best_by_sig.get(sig)
                    if old is None or g.confidence > old.confidence:
                        best_by_sig[sig] = g

        # 3) 英文地域规则兜底
        english_region_rules = {
            r"\beast\s+china\b": "华东",
            r"\bnorth\s+china\b": "华北",
            r"\bsouth\s+china\b": "华南",
        }
        for pat, canon in english_region_rules.items():
            if re.search(pat, q, flags=re.IGNORECASE):
                g = GroundedEntity(
                    original_term=pat,
                    entity_type="region",
                    canonical_name=canon,
                    mappings={"sql": {"region": canon}},
                    confidence=0.86,
                    alternatives=[],
                )
                sig = (g.entity_type, g.canonical_name)
                old = best_by_sig.get(sig)
                if old is None or g.confidence > old.confidence:
                    best_by_sig[sig] = g

        # 4) 冲突消解优先级：time_range > region > metric > unknown
        priority = {"time_range": 0, "region": 1, "metric": 2, "unknown": 99}
        matched = sorted(
            best_by_sig.values(),
            key=lambda x: (priority.get(x.entity_type, 50), -x.confidence, x.canonical_name),
        )

        return matched

    def _ground_time_phrase(self, phrase: str) -> dict | None:
        p = (phrase or "").strip().lower()
        today = date.today()

        if p in {"今天", "today"}:
            return {
                "canonical_name": "today",
                "mappings": {"time_expr": "today", "start_date": str(today), "end_date": str(today)},
                "alternatives": ["当日"],
            }
        if p in {"昨天", "昨日", "yesterday"}:
            d = today - timedelta(days=1)
            return {
                "canonical_name": "yesterday",
                "mappings": {"time_expr": "yesterday", "start_date": str(d), "end_date": str(d)},
                "alternatives": ["前一日"],
            }
        if p in {"上周", "last week"}:
            end = today - timedelta(days=today.weekday() + 1)
            start = end - timedelta(days=6)
            return {
                "canonical_name": "last_week",
                "mappings": {"time_expr": "last_week", "start_date": str(start), "end_date": str(end)},
            }
        if p in {"本周", "this week"}:
            start = today - timedelta(days=today.weekday())
            return {
                "canonical_name": "this_week",
                "mappings": {"time_expr": "this_week", "start_date": str(start), "end_date": str(today)},
            }
        if p in {"本月", "this month"}:
            start = today.replace(day=1)
            return {
                "canonical_name": "this_month",
                "mappings": {"time_expr": "this_month", "start_date": str(start), "end_date": str(today)},
            }
        if p in {"上月", "last month"}:
            first_this_month = today.replace(day=1)
            end_last_month = first_this_month - timedelta(days=1)
            start_last_month = end_last_month.replace(day=1)
            return {
                "canonical_name": "last_month",
                "mappings": {"time_expr": "last_month", "start_date": str(start_last_month), "end_date": str(end_last_month)},
            }
        if p in {"上季度", "上一季度", "last quarter"}:
            return {
                "canonical_name": "last_quarter",
                "mappings": {"time_expr": "last_quarter"},
                "alternatives": ["q-1"],
            }
        if p in {"本季度", "this quarter"}:
            return {
                "canonical_name": "this_quarter",
                "mappings": {"time_expr": "this_quarter"},
            }
        if p in {"今年", "this year"}:
            start = today.replace(month=1, day=1)
            return {
                "canonical_name": "this_year",
                "mappings": {"time_expr": "this_year", "start_date": str(start), "end_date": str(today)},
            }
        if p in {"去年", "last year"}:
            start = date(today.year - 1, 1, 1)
            end = date(today.year - 1, 12, 31)
            return {
                "canonical_name": "last_year",
                "mappings": {"time_expr": "last_year", "start_date": str(start), "end_date": str(end)},
            }

        return None
