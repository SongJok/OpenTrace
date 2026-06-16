"""
矛盾检测器 — 检测和解决记忆之间的冲突。

当系统学习到与现有记忆矛盾的新事实时，
此模块检测矛盾并通过以下方式解决：
- 标记矛盾供人工审核（严重）
- 按置信度比较自动解决（中等）
- 带注意事项合并（轻微）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ResolutionAction(str, Enum):
    KEEP_BOTH = "keep_both"           # 两者均有效，上下文不同
    PREFER_NEWER = "prefer_newer"     # 较新事实取代较旧事实
    PREFER_HIGHER_CONFIDENCE = "prefer_higher_confidence"
    FLAG_HUMAN = "flag_human"         # 需要人工判断
    MERGE_WITH_CAVEAT = "merge"       # 带不确定性注意事项合并


@dataclass
class MemoryContradiction:
    """检测到的两个记忆之间的矛盾。"""
    memory_a_id: str = ""
    memory_b_id: str = ""
    memory_a_content: str = ""
    memory_b_content: str = ""
    contradiction_type: str = "factual"  # factual | temporal | preference | semantic
    severity: str = "moderate"  # minor | moderate | critical
    resolution: ResolutionAction = ResolutionAction.FLAG_HUMAN
    resolution_note: str = ""
    auto_resolved: bool = False


class ContradictionDetector:
    """使用启发式 + 语义分析检测记忆间的矛盾。

    对于高严重性情况，建议使用 LLM 验证。
    """

    def detect(
        self,
        existing_memories: list[dict[str, Any]],
        new_memory: dict[str, Any],
    ) -> list[MemoryContradiction]:
        """检测新记忆与现有记忆之间的矛盾。

        返回发现的矛盾列表，无矛盾则为空。
        """
        contradictions: list[MemoryContradiction] = []

        new_content = str(new_memory.get("content", "") or new_memory.get("description", ""))
        new_type = str(new_memory.get("memory_type", "fact"))
        new_confidence = float(new_memory.get("confidence", 0.5))
        new_id = str(new_memory.get("memory_id", "new"))

        if not new_content.strip():
            return []

        for existing in existing_memories:
            existing_id = str(existing.get("memory_id", ""))
            existing_content = str(existing.get("content", "") or existing.get("description", ""))
            existing_type = str(existing.get("memory_type", "fact"))
            existing_confidence = float(existing.get("confidence", 0.5))

            if not existing_content.strip():
                continue
            if existing_id == new_id:
                continue

            # 仅检查同类型记忆
            if existing_type != new_type and new_type != "fact":
                continue

            # 检测矛盾
            contradiction = self._check_contradiction(
                new_id, new_content, new_type, new_confidence,
                existing_id, existing_content, existing_type, existing_confidence,
            )
            if contradiction:
                contradictions.append(contradiction)

        return contradictions

    def resolve(
        self, contradictions: list[MemoryContradiction]
    ) -> list[MemoryContradiction]:
        """尝试自动解决矛盾。

        返回已应用解决的矛盾列表。
        """
        for c in contradictions:
            if c.severity == "critical":
                c.resolution = ResolutionAction.FLAG_HUMAN
                c.auto_resolved = False
            elif c.severity == "moderate":
                c.resolution = ResolutionAction.PREFER_HIGHER_CONFIDENCE
                c.auto_resolved = True
            else:  # minor
                c.resolution = ResolutionAction.MERGE_WITH_CAVEAT
                c.auto_resolved = True

        return contradictions

    # ── 内部方法 ─────────────────────────────────────────────────────────────

    def _check_contradiction(
        self,
        new_id: str, new_content: str, new_type: str, new_conf: float,
        existing_id: str, existing_content: str, existing_type: str, existing_conf: float,
    ) -> MemoryContradiction | None:
        # 步骤 1：检查明确的矛盾关键词
        if _has_explicit_contradiction(new_content, existing_content):
            return MemoryContradiction(
                memory_a_id=existing_id,
                memory_b_id=new_id,
                memory_a_content=existing_content[:200],
                memory_b_content=new_content[:200],
                contradiction_type="factual",
                severity="critical",
            )

        # 步骤 2：检查时间矛盾（同一实体，不同时间声明）
        if _has_temporal_conflict(new_content, existing_content):
            return MemoryContradiction(
                memory_a_id=existing_id,
                memory_b_id=new_id,
                memory_a_content=existing_content[:200],
                memory_b_content=new_content[:200],
                contradiction_type="temporal",
                severity="moderate",
            )

        # 步骤 3：检查同一实体但置信度分歧
        overlap = _entity_overlap(new_content, existing_content)
        if overlap > 0.6 and abs(new_conf - existing_conf) > 0.5:
            return MemoryContradiction(
                memory_a_id=existing_id,
                memory_b_id=new_id,
                memory_a_content=existing_content[:200],
                memory_b_content=new_content[:200],
                contradiction_type="factual",
                severity="moderate",
            )

        return None


def _has_explicit_contradiction(text_a: str, text_b: str) -> bool:
    """检查明确的矛盾信号。"""
    contradiction_patterns = [
        (["是", "对", "正确", "yes", "true", "correct", "可以", "已", "已经", "已上"],
         ["不是", "不对", "错误", "no", "false", "incorrect", "不可以", "无法", "还没有", "还没", "未", "尚未"]),
        (["增加", "上升", "增长", "提高", "increase", "rise", "grow", "higher"],
         ["减少", "下降", "降低", "减少", "decrease", "fall", "drop", "lower"]),
    ]

    a_lower = text_a.lower()
    b_lower = text_b.lower()

    for pos_terms, neg_terms in contradiction_patterns:
        a_pos = any(t in a_lower for t in pos_terms)
        a_neg = any(t in a_lower for t in neg_terms)
        b_pos = any(t in b_lower for t in pos_terms)
        b_neg = any(t in b_lower for t in neg_terms)

        if (a_pos and b_neg) or (a_neg and b_pos):
            return True

    # 数值矛盾：相同实体上下文，不同数字
    import re
    nums_a = re.findall(r'\d[\d,.]*万?亿?千?百?', text_a)
    nums_b = re.findall(r'\d[\d,.]*万?亿?千?百?', text_b)
    if nums_a and nums_b and nums_a != nums_b:
        # 检查文本是否关于同一主题
        if _entity_overlap(text_a, text_b) > 0.3:
            return True

    return False


def _has_temporal_conflict(text_a: str, text_b: str) -> bool:
    """检查两个记忆是否对同一实体做出不同的时间声明。"""
    import re

    # 提取日期模式
    date_pattern = r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?|\d{4}[-/]\d{1,2}|\d{1,2}月\d{1,2}[日号]'
    dates_a = re.findall(date_pattern, text_a)
    dates_b = re.findall(date_pattern, text_b)

    if not dates_a or not dates_b:
        return False

    # 不同日期 + 高实体重叠 = 潜在时间冲突
    if set(dates_a) != set(dates_b) and _entity_overlap(text_a, text_b) > 0.4:
        return True

    return False


def _entity_overlap(text_a: str, text_b: str) -> float:
    import re

    def _entities(text: str) -> set[str]:
        entities: set[str] = set()
        entities.update(re.findall(r'[A-Z][a-z]{2,}', text))
        entities.update(re.findall(r'[一-鿿]{2,4}', text))
        entities.update(re.findall(r'\d{2,}', text))
        return entities

    ea = _entities(text_a)
    eb = _entities(text_b)
    if not ea or not eb:
        return 0.0
    return len(ea & eb) / len(ea | eb)
