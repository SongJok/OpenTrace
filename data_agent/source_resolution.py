"""基于企业证据而不是列表顺序选择可信数据源。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from data_agent.contracts import DataSourceCandidate, DataSourceDecision


def _tokens(value: str) -> set[str]:
    text = str(value or "").lower()
    result = set(re.findall(r"[a-z0-9_]+", text))
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        result.add(segment)
        result.update(segment[index : index + 2] for index in range(len(segment) - 1))
    return {item for item in result if item}


@dataclass(frozen=True)
class SourceSignal:
    kind: str
    source_id: str
    text: str
    certified: bool = False
    blocked: bool = False


@dataclass
class SourceCatalogEntry:
    data_source_id: str
    name: str
    source_type: str
    schema_synced: bool = False
    profile_current: bool = False
    signals: list[SourceSignal] = field(default_factory=list)


class TrustedSourceSelector:
    """优先选择被指标、业务语义和执行事实共同支持的数据源。"""

    _relevance_weights = {
        "metric": 5.0,
        "semantic": 4.0,
        "report": 4.0,
        "lineage": 3.5,
        "sql_asset": 3.0,
        "schema": 2.0,
        "execution_memory": 2.0,
        "source_name": 1.0,
    }

    def __init__(self, *, minimum_score: float = 0.25, ambiguity_delta: float = 0.08) -> None:
        self.minimum_score = minimum_score
        self.ambiguity_delta = ambiguity_delta

    def select(
        self,
        question: str,
        entries: list[SourceCatalogEntry],
        *,
        explicit_id: str | None = None,
    ) -> DataSourceDecision:
        candidates = [self._score(question, entry) for entry in entries]
        candidates.sort(
            key=lambda item: (-item.score, -item.trust_score, item.name, item.data_source_id)
        )
        if explicit_id:
            explicit = next(
                (item for item in candidates if item.data_source_id == explicit_id), None
            )
            if explicit is None or explicit.blocked:
                return DataSourceDecision(
                    status="no_source",
                    question=question,
                    reason="指定数据源不存在、未授权或被治理策略阻止",
                    candidates=candidates,
                )
            return self._selected(question, explicit, candidates, reason="用户明确指定数据源")

        selectable = [item for item in candidates if not item.blocked]
        if not selectable:
            return DataSourceDecision(
                status="no_source",
                question=question,
                reason="没有可用于该问题的授权数据源",
                candidates=candidates,
            )
        if len(selectable) == 1:
            return self._selected(
                question,
                selectable[0],
                candidates,
                reason="当前作用域只有一个可查询数据源",
            )

        top = selectable[0]
        second = selectable[1]
        delta = top.score - second.score
        if top.relevance_score <= 0 or top.score < self.minimum_score:
            return DataSourceDecision(
                status="needs_clarification",
                question=question,
                confidence=max(0.0, min(1.0, top.score)),
                reason="没有数据源获得足够的业务指标、语义或历史执行证据支持",
                candidates=candidates,
            )
        if delta < self.ambiguity_delta and second.relevance_score > 0:
            return DataSourceDecision(
                status="needs_clarification",
                question=question,
                confidence=max(0.0, min(1.0, 0.5 + delta)),
                reason="多个数据源获得接近的企业证据评分，需要用户确认业务范围",
                candidates=candidates,
            )
        return self._selected(
            question,
            top,
            candidates,
            reason="根据认证指标、业务语义、血缘、Schema 和成功执行证据自动选择",
        )

    @staticmethod
    def _selected(
        question: str,
        selected: DataSourceCandidate,
        candidates: list[DataSourceCandidate],
        *,
        reason: str,
    ) -> DataSourceDecision:
        return DataSourceDecision(
            status="selected",
            question=question,
            selected_data_source_id=selected.data_source_id,
            selected_data_source_name=selected.name,
            confidence=selected.score,
            reason=reason,
            candidates=candidates,
        )

    def _score(self, question: str, entry: SourceCatalogEntry) -> DataSourceCandidate:
        question_tokens = _tokens(question)
        relevance_points = 0.0
        evidence_ids: list[str] = []
        reasons: list[str] = []
        matched_terms: set[str] = set()
        kinds: set[str] = set()
        blocked = False
        certified_metric = False
        for signal in entry.signals:
            blocked = blocked or signal.blocked
            signal_tokens = _tokens(signal.text)
            matches = question_tokens.intersection(signal_tokens)
            if not matches:
                continue
            weight = self._relevance_weights.get(signal.kind, 1.0)
            coverage = min(1.0, len(matches) / max(1, min(4, len(question_tokens))))
            relevance_points += weight * (0.5 + 0.5 * coverage)
            evidence_ids.append(signal.source_id)
            matched_terms.update(matches)
            kinds.add(signal.kind)
            certified_metric = certified_metric or (signal.kind == "metric" and signal.certified)

        trust = 0.10
        if entry.schema_synced:
            trust += 0.15
        if entry.profile_current:
            trust += 0.05
        signal_kinds = {signal.kind for signal in entry.signals}
        if "metric" in signal_kinds:
            trust += (
                0.25
                if any(signal.kind == "metric" and signal.certified for signal in entry.signals)
                else 0.12
            )
        if "semantic" in signal_kinds or "report" in signal_kinds:
            trust += 0.15
        if "lineage" in signal_kinds:
            trust += 0.10
        if "sql_asset" in signal_kinds:
            trust += 0.10
        if "execution_memory" in signal_kinds:
            trust += 0.10
        trust_score = min(1.0, trust)
        relevance_score = min(1.0, relevance_points / 12.0)
        score = min(1.0, relevance_score * 0.72 + trust_score * 0.28)

        if certified_metric and "metric" in kinds:
            reasons.append("命中公司认证指标")
        if "semantic" in kinds:
            reasons.append("命中已发布业务规则或语义资产")
        if "report" in kinds:
            reasons.append("命中已发布报表口径")
        if "lineage" in kinds:
            reasons.append("命中可信血缘资产")
        if "sql_asset" in kinds:
            reasons.append("命中已验证历史 SQL")
        if "execution_memory" in kinds:
            reasons.append("命中相同作用域的成功执行经验")
        if entry.schema_synced:
            reasons.append("Schema 已同步")
        if blocked:
            reasons.append("数据源策略禁止生成或执行")
            score = 0.0

        return DataSourceCandidate(
            data_source_id=entry.data_source_id,
            name=entry.name,
            source_type=entry.source_type,
            score=score,
            relevance_score=relevance_score,
            trust_score=trust_score,
            blocked=blocked,
            reasons=list(dict.fromkeys(reasons)),
            evidence_ids=list(dict.fromkeys(evidence_ids))[:50],
            matched_terms=sorted(matched_terms)[:30],
        )
