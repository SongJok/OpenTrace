"""
证据冲突解决 — 证据融合中的冲突检测与解决。

当多个证据来源给出矛盾答案时，此模块：
1. 检测矛盾（证据项之间的事实分歧）
2. 按严重程度分类矛盾
3. 通过策略解决：最高置信度优先、多数投票、或标记人工审核
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


class ResolutionStrategy(str, Enum):
    HIGHEST_CONFIDENCE = "highest_confidence"  # 信任最高置信度的来源
    MAJORITY_VOTE = "majority_vote"            # 多数胜出
    SOURCE_AUTHORITY = "source_authority"       # 优先权威来源
    FLAG_HUMAN = "flag_human"                   # 无法自动解决
    KEEP_BOTH = "keep_both"                     # 两者均有效，不同视角


@dataclass
class EvidenceConflict:
    """检测到的两个证据项之间的矛盾。"""
    evidence_a_id: str = ""
    evidence_b_id: str = ""
    description: str = ""
    severity: str = "minor"  # minor | moderate | critical
    resolved: bool = False
    resolution_strategy: str = ""
    winner_id: str = ""
    resolution_note: str = ""


@dataclass
class EvidenceResolution:
    """解决证据集中所有冲突的结果。"""
    resolved_evidence_ids: list[str] = field(default_factory=list)
    conflicts: list[EvidenceConflict] = field(default_factory=list)
    resolved_count: int = 0
    unresolved_count: int = 0
    flagged_for_human: list[str] = field(default_factory=list)


def resolve_evidence_conflicts(
    ranked_evidence: list[Any],
    strategy: ResolutionStrategy = ResolutionStrategy.HIGHEST_CONFIDENCE,
) -> EvidenceResolution:
    """解决排序证据中的冲突。

    目前使用启发式方法：语义重叠 + 置信度比较。
    完整的语义矛盾检测需要 LLM，仅在高严重性潜在冲突时触发。
    """
    if len(ranked_evidence) <= 1:
        ids = [getattr(e, "evidence_id", "") for e in ranked_evidence]
        return EvidenceResolution(
            resolved_evidence_ids=ids,
            resolved_count=len(ids),
        )

    conflicts = _detect_conflicts(ranked_evidence)
    resolved_ids = _apply_resolution(ranked_evidence, conflicts, strategy)

    resolved = sum(1 for c in conflicts if c.resolved)
    unresolved = len(conflicts) - resolved
    flagged = [c.evidence_a_id for c in conflicts if not c.resolved]

    return EvidenceResolution(
        resolved_evidence_ids=resolved_ids,
        conflicts=conflicts,
        resolved_count=resolved,
        unresolved_count=unresolved,
        flagged_for_human=flagged,
    )


def _detect_conflicts(evidence_list: list[Any]) -> list[EvidenceConflict]:
    """启发式冲突检测：语义重叠 + 置信度分歧。"""
    conflicts: list[EvidenceConflict] = []

    for i in range(len(evidence_list)):
        for j in range(i + 1, len(evidence_list)):
            ev_a = evidence_list[i]
            ev_b = evidence_list[j]

            content_a = getattr(ev_a, "content", "")
            content_b = getattr(ev_b, "content", "")
            conf_a = getattr(ev_a, "credibility_score", 0.5)
            conf_b = getattr(ev_b, "credibility_score", 0.5)
            source_a = _get_source(ev_a)
            source_b = _get_source(ev_b)

            # 两者置信度都很低则跳过
            if conf_a < 0.3 and conf_b < 0.3:
                continue

            # 检测潜在矛盾：相同主题、置信度分歧或矛盾关键词
            overlap = _topic_overlap(content_a, content_b)

            if overlap > 0.3 and abs(conf_a - conf_b) > 0.4:
                severity = "critical" if abs(conf_a - conf_b) > 0.6 else "moderate"
                conflicts.append(EvidenceConflict(
                    evidence_a_id=getattr(ev_a, "evidence_id", ""),
                    evidence_b_id=getattr(ev_b, "evidence_id", ""),
                    description=f"Confidence divergence: {source_a}({conf_a:.2f}) vs {source_b}({conf_b:.2f})",
                    severity=severity,
                ))
            elif _has_contradictory_keywords(content_a, content_b):
                conflicts.append(EvidenceConflict(
                    evidence_a_id=getattr(ev_a, "evidence_id", ""),
                    evidence_b_id=getattr(ev_b, "evidence_id", ""),
                    description=f"Contradictory content between {source_a} and {source_b}",
                    severity="critical",
                ))

    return conflicts


def _apply_resolution(
    evidence_list: list[Any],
    conflicts: list[EvidenceConflict],
    strategy: ResolutionStrategy,
) -> list[str]:
    """应用解决策略以保留/丢弃证据。"""
    keep_ids = {getattr(e, "evidence_id", "") for e in evidence_list}
    drop_ids: set[str] = set()

    for conflict in conflicts:
        ev_a = next(
            (e for e in evidence_list if getattr(e, "evidence_id", "") == conflict.evidence_a_id),
            None,
        )
        ev_b = next(
            (e for e in evidence_list if getattr(e, "evidence_id", "") == conflict.evidence_b_id),
            None,
        )
        if ev_a is None or ev_b is None:
            continue

        conf_a = getattr(ev_a, "credibility_score", 0.5)
        conf_b = getattr(ev_b, "credibility_score", 0.5)

        if strategy == ResolutionStrategy.HIGHEST_CONFIDENCE:
            if conf_a >= conf_b:
                drop_ids.add(conflict.evidence_b_id)
                conflict.winner_id = conflict.evidence_a_id
            else:
                drop_ids.add(conflict.evidence_a_id)
                conflict.winner_id = conflict.evidence_b_id
            conflict.resolution_strategy = "highest_confidence"
            conflict.resolved = True

        elif strategy == ResolutionStrategy.SOURCE_AUTHORITY:
            auth_a = _get_authority(_get_source(ev_a))
            auth_b = _get_authority(_get_source(ev_b))
            if auth_a >= auth_b:
                drop_ids.add(conflict.evidence_b_id)
                conflict.winner_id = conflict.evidence_a_id
            else:
                drop_ids.add(conflict.evidence_a_id)
                conflict.winner_id = conflict.evidence_b_id
            conflict.resolution_strategy = "source_authority"
            conflict.resolved = True

        elif strategy == ResolutionStrategy.MAJORITY_VOTE:
            # 模拟：保留有更多支持证据的（同来源组）
            # 简化：保留更高置信度的
            if conf_a >= conf_b:
                drop_ids.add(conflict.evidence_b_id)
                conflict.winner_id = conflict.evidence_a_id
            else:
                drop_ids.add(conflict.evidence_a_id)
                conflict.winner_id = conflict.evidence_b_id
            conflict.resolution_strategy = "majority_vote"
            conflict.resolved = True

        elif strategy == ResolutionStrategy.FLAG_HUMAN:
            conflict.resolved = False
            conflict.resolution_strategy = "flag_human"

        elif strategy == ResolutionStrategy.KEEP_BOTH:
            conflict.resolved = True
            conflict.resolution_strategy = "keep_both"

    return list(keep_ids - drop_ids)


_AUTHORITY_MAP: dict[str, float] = {
    "data": 0.9, "rag": 0.7, "skills": 0.8, "web": 0.5,
    "tool": 0.7, "rule_engine": 0.8, "vision": 0.6,
}


def _get_source(evidence: Any) -> str:
    provenance = getattr(evidence, "provenance", None)
    if provenance:
        return getattr(provenance, "source", "unknown")
    return getattr(evidence, "source", "unknown")


def _get_authority(source: str) -> float:
    return _AUTHORITY_MAP.get(source.lower(), 0.5)


def _topic_overlap(text_a: str, text_b: str) -> float:
    """通过 token 交集计算主题重叠度。"""
    import re

    def _tokens(text: str) -> set[str]:
        lowered = text.lower()
        tokens: set[str] = set()
        tokens.update(re.findall(r'[a-z]{3,}', lowered))
        tokens.update(re.findall(r'[一-鿿]{2,}', lowered))
        return tokens

    ta = _tokens(text_a)
    tb = _tokens(text_b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _has_contradictory_keywords(text_a: str, text_b: str) -> bool:
    """检查是否存在明确的矛盾指示词。"""
    contradiction_pairs = [
        (["是", "对", "正确", "yes", "true", "correct"],
         ["不是", "不对", "错误", "no", "false", "incorrect", "无法"]),
        (["增加", "上升", "增长", "increase", "rise", "grow"],
         ["减少", "下降", "降低", "decrease", "fall", "drop"]),
    ]

    for pos_words, neg_words in contradiction_pairs:
        a_positive = any(w in text_a.lower() for w in pos_words)
        a_negative = any(w in text_a.lower() for w in neg_words)
        b_positive = any(w in text_b.lower() for w in pos_words)
        b_negative = any(w in text_b.lower() for w in neg_words)

        if (a_positive and b_negative) or (a_negative and b_positive):
            return True

    return False
