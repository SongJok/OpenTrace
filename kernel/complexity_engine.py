"""复杂度引擎 — 轻量启发式查询复杂度评估。

根据长度、实体数、推理关键词等将查询路由到合适层级：
  - L0：极简单（问候、单词）→ 规则路由
  - L1：中等复杂 → 小型 LLM 路由
  - v4：复杂查询 → 完整 V4 编排流水线
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# 表示需要推理/分析的关键词
_REASONING_KW = {
    "分析", "对比", "比较", "为什么", "原因", "解释", "说明",
    "总结", "归纳", "概括", "趋势", "关系", "影响", "建议",
    "分析报告", "如何", "怎么", "怎样", "方案", "策略",
    "compare", "analyze", "explain", "why", "how",
    "trend", "summary", "difference", "versus", "vs",
}

# 表示简单事实查询的关键词
_FACTUAL_KW = {
    "什么是", "是谁", "定义", "意思", "全称", "缩写",
    "what is", "who is", "define",
}

# 问候/对话模式
_GREETING_PATTERNS = re.compile(
    r"^(你好|您好|hi|hello|hey|早上好|晚上好|再见|bye|谢谢|thank|ok|好的)[!！。.]?$",
    re.IGNORECASE,
)

_SIMPLE_HELP_PATTERNS = re.compile(
    r"(你能做什么|你可以做什么|你有哪些?功能|你会什么|你能干什么|"
    r"你能帮我.*什么|怎么帮我|如何帮我|可以帮我什么|怎么用|怎么使用|帮助|help)",
    re.IGNORECASE,
)


@dataclass
class ComplexityAssessment:
    recommended_pipeline: str = "v4"  # "L0" | "L1" | "v4"
    level: str = "complex"           # "simple" | "medium" | "complex"
    score: float = 0.0               # 0.0-1.0

    def __repr__(self) -> str:
        return (
            f"ComplexityAssessment(pipeline={self.recommended_pipeline}, "
            f"level={self.level}, score={self.score:.2f})"
        )


class ComplexityEngine:
    """启发式查询复杂度评估器 — 不调用 LLM，纯规则驱动。"""

    def assess(
        self,
        query: str,
        conversation_context: dict | None = None,
    ) -> ComplexityAssessment:
        if not query or not query.strip():
            return ComplexityAssessment(
                recommended_pipeline="L0", level="simple", score=0.0,
            )

        text = query.strip()
        text_lower = text.lower()

        # ── 问候快速路径 ──
        if _GREETING_PATTERNS.match(text):
            return ComplexityAssessment(
                recommended_pipeline="L0", level="simple", score=0.05,
            )
        if _SIMPLE_HELP_PATTERNS.search(text):
            return ComplexityAssessment(
                recommended_pipeline="L0", level="simple", score=0.05,
            )

        # ── 特征提取 ──
        char_len = len(text)

        # 统计实体：专有名词、数字、日期、技术术语
        entities = set()
        entities.update(re.findall(r'[A-Z][a-z]{2,}', text))       # 英文专有名词
        entities.update(re.findall(r'[一-鿿]{2,4}', text))  # 中文二元组
        entities.update(re.findall(r'\d{2,}', text))                 # 多位数字
        entity_count = len(entities)

        # 统计子句（句子片段）
        clause_separators = len(re.findall(r'[，,;；。！？!?\n]', text))
        clause_count = max(1, clause_separators)

        # 推理关键词
        reasoning_hits = sum(1 for kw in _REASONING_KW if kw in text_lower)
        factual_hits = sum(1 for kw in _FACTUAL_KW if kw in text_lower)

        # ── 评分 ──
        # 长度因子：将 0-500 字符映射到 0-1
        length_score = min(char_len / 500.0, 1.0)

        # 实体因子：每个不同实体增加约 0.1，最大 1.0
        entity_score = min(entity_count * 0.1, 1.0)

        # 子句因子：子句越多越复杂
        clause_score = min(clause_count * 0.15, 1.0)

        # 推理因子
        reasoning_bonus = min(reasoning_hits * 0.2, 0.5)
        factual_discount = min(factual_hits * 0.1, 0.2)

        score = (
            length_score * 0.35
            + entity_score * 0.25
            + clause_score * 0.20
            + reasoning_bonus
            - factual_discount
        )
        score = max(0.0, min(score, 1.0))

        # ── 流水线路由 ──
        if score < 0.3:
            pipeline = "L0"
            level = "simple"
        elif score < 0.6:
            pipeline = "L1"
            level = "medium"
        else:
            pipeline = "v4"
            level = "complex"

        return ComplexityAssessment(
            recommended_pipeline=pipeline,
            level=level,
            score=round(score, 3),
        )
