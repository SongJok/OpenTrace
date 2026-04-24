from __future__ import annotations

from .models import FusionInput, FusionOutput, ToolResult


class FusionEngine:
    _weights = {
        "llmwiki": 1.05,
        "document": 0.72,
        "sql": 1.0,
        "weather": 0.9,
        "time": 0.9,
        "search": 0.6,
        "web_search": 0.6,
    }

    def _weight(self, source: str) -> float:
        return self._weights.get((source or "").lower(), 0.5)

    def _priority_bonus(self, result: ToolResult) -> float:
        priority = max(1, int(getattr(result, "source_priority", 10) or 10))
        return max(0.0, 0.14 - ((priority - 1) * 0.03))

    def _freshness_bonus(self, source: str, adaptive_profile: dict[str, object]) -> float:
        profile_name = str((adaptive_profile or {}).get("name", "balanced") or "balanced")
        if profile_name == "speed":
            return 0.05 if source in {"time", "weather", "web_search"} else 0.0
        if profile_name == "quality":
            return 0.08 if source in {"sql", "document"} else 0.03 if source in {"web_search", "search"} else 0.0
        return 0.0

    def _render_context(self, picked: dict[str, ToolResult]) -> str:
        lines: list[str] = []
        for src, r in picked.items():
            text = str(r.data)
            if src == "document" and (text.strip().startswith("{") or "'chunks'" in text or '"chunks"' in text):
                text = "未检索到可直接引用的内部文档内容。"
            lines.append(f"[{src}] {text[:1200]}")
        return "\n".join(lines)

    def run(self, input_data: FusionInput) -> FusionOutput:
        if not input_data.results:
            return FusionOutput(merged_context="", conflicts=[], confidence=0.0)

        profile = input_data.adaptive_profile or {}
        profile_name = str(profile.get("name", "balanced") or "balanced")
        conflict_mode = profile_name == "quality"
        diversity_mode = profile_name != "speed"

        picked: dict[str, ToolResult] = {}
        alternates: list[str] = []
        evidence_map: list[dict[str, object]] = []
        conflicts: list[str] = []
        for r in input_data.results:
            key = (r.source or "unknown").lower()
            evidence_map.append({"source": key, "confidence": r.confidence, "preview": str(r.data)[:300]})
            if key not in picked:
                picked[key] = r
                continue
            prev = picked[key]
            if str(prev.data) != str(r.data):
                conflicts.append(f"conflict:{key}")
                prev_score = (prev.confidence or 0.5) + self._weight(key) + self._freshness_bonus(key, profile) + self._priority_bonus(prev)
                curr_score = (r.confidence or 0.5) + self._weight(key) + self._freshness_bonus(key, profile) + self._priority_bonus(r)
                if curr_score > prev_score:
                    alternates.append(f"[{key}] {str(prev.data)[:500]}")
                    picked[key] = r
                else:
                    alternates.append(f"[{key}] {str(r.data)[:500]}")
                if conflict_mode and abs(curr_score - prev_score) < 0.12:
                    alternates.append(f"[{key}] 分歧接近，保留多个候选来源")

        if diversity_mode and len(picked) > 1:
            ordered = sorted(
                picked.items(),
                key=lambda item: (item[1].confidence or 0.5) + self._weight(item[0]) + self._freshness_bonus(item[0], profile) + self._priority_bonus(item[1]),
                reverse=True,
            )
            picked = dict(ordered[:4])

        merged_context = self._render_context(picked)
        conf = 0.0
        if picked:
            weight_sum = sum(self._weight(src) + self._freshness_bonus(src, profile) + self._priority_bonus(r) for src, r in picked.items())
            if weight_sum <= 0:
                weight_sum = float(len(picked))
            conf = sum((r.confidence or 0.5) * (self._weight(src) + self._freshness_bonus(src, profile) + self._priority_bonus(r)) for src, r in picked.items()) / weight_sum
            if profile_name == "quality" and len(picked) >= 2:
                conf = min(1.0, conf + 0.05)
            conf = max(0.0, min(1.0, conf))

        if conflict_mode and alternates and len(alternates) >= 1:
            merged_context = merged_context + "\n\n[disagreement]\n" + "\n".join(alternates[:3])

        return FusionOutput(
            merged_context=merged_context,
            conflicts=sorted(set(conflicts)),
            confidence=conf,
            alternate_contexts=alternates[:3],
            evidence_map=evidence_map,
        )
