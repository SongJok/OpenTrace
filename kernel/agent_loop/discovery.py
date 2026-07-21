from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from kernel.agent_loop.contracts import ToolSpec


@dataclass(frozen=True)
class CapabilityMatch:
    name: str
    description: str
    score: float
    side_effect: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "score": round(self.score, 4),
            "side_effect": self.side_effect,
        }


@dataclass(frozen=True)
class DiscoveryResult:
    specs: tuple[ToolSpec, ...]
    matches: tuple[CapabilityMatch, ...]
    total_available: int

    def prompt_catalogue(self) -> list[dict[str, Any]]:
        return [
            {
                "name": match.name,
                "description": match.description,
                "side_effect": match.side_effect,
            }
            for match in self.matches
        ]


class CapabilityDiscovery:
    """在可信注册表内做查询相关性发现，模型不能借此扩大权限边界。"""

    def __init__(self, *, catalogue_limit: int = 48):
        self.catalogue_limit = max(8, catalogue_limit)

    def discover(
        self,
        query: str,
        specs: list[ToolSpec],
        *,
        pinned_names: set[str] | None = None,
    ) -> DiscoveryResult:
        pinned = pinned_names or set()
        query_terms = self._terms(query)
        ranked: list[tuple[float, int, ToolSpec]] = []
        for index, spec in enumerate(specs):
            document = " ".join(
                (
                    spec.name.replace("_", " "),
                    spec.description,
                    " ".join((spec.parameters.get("properties") or {}).keys()),
                )
            )
            document_terms = self._terms(document)
            overlap = len(query_terms & document_terms) / max(1, len(query_terms))
            exact = 1.0 if spec.name.lower() in query.lower() else 0.0
            name_terms = self._terms(spec.name.replace("_", " "))
            name_overlap = len(query_terms & name_terms) / max(1, len(name_terms))
            score = overlap * 5.0 + name_overlap * 2.0 + exact * 4.0
            if spec.name in pinned:
                score += 100.0
            ranked.append((score, -index, spec))

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        positive = [item for item in ranked if item[0] > 0]
        # 小目录完整交给规划器；目录扩展后只暴露相关能力和调用方显式工具，
        # 避免工具 schema 吞噬长上下文。
        selected = (
            ranked if len(ranked) <= self.catalogue_limit else positive[: self.catalogue_limit]
        )
        if not selected:
            selected = ranked[: self.catalogue_limit]
        selected_names = {item[2].name for item in selected}
        for item in ranked:
            if item[2].name in pinned and item[2].name not in selected_names:
                selected.append(item)
                selected_names.add(item[2].name)
        matches = tuple(
            CapabilityMatch(
                name=spec.name,
                description=spec.description[:500],
                score=score,
                side_effect=spec.side_effect.value,
            )
            for score, _index, spec in selected
        )
        return DiscoveryResult(
            specs=tuple(spec for _score, _index, spec in selected),
            matches=matches,
            total_available=len(specs),
        )

    @staticmethod
    def _terms(text: str) -> set[str]:
        lowered = text.lower()
        terms = set(re.findall(r"[a-z0-9_]{2,}", lowered))
        for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
            terms.add(run)
            if len(run) == 1:
                continue
            terms.update(run[index : index + 2] for index in range(len(run) - 1))
        return terms
