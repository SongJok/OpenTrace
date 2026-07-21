"""
上下文排序器 — 基于相关性的 LLM 提示词上下文块排序。

对上下文块（记忆、历史、偏好、数据源）按与当前查询的相关性
进行评分和排序。高相关性块在 token 预算中获得优先权。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RankedContextBlock:
    """带有相关性评分和排名的上下文块。"""
    content: str
    source_type: str  # "memory" | "history" | "preferences" | "data_source" | "attachment"
    relevance_score: float = 0.5
    rank: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class ContextRanker:
    """基于 BM25 思路的上下文块相关性排序器。

    对每个块相对于查询评分，然后按相关性排序。
    无需 LLM 调用 — 纯词法 + 启发式。
    """

    def __init__(self) -> None:
        pass

    def rank(
        self,
        query: str,
        blocks: list[RankedContextBlock],
        top_k: int = 10,
    ) -> list[RankedContextBlock]:
        """按与查询的相关性对上下文块排序。

        Args:
            query: 用于评分的用户查询。
            blocks: 已填充内容的上下文块。
            top_k: 返回的最大块数。

        Returns:
            按 relevance_score 降序排列的排序块。
        """
        if not blocks:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            for i, b in enumerate(blocks):
                b.rank = i
                b.relevance_score = 0.5
            return blocks[:top_k]

        # 对每个块评分
        for block in blocks:
            block.relevance_score = self._score(query_tokens, block)
            block.rank = 0  # 排序后设置

        # 按相关性排序
        blocks.sort(key=lambda b: b.relevance_score, reverse=True)

        # 设置排名
        for i, b in enumerate(blocks):
            b.rank = i + 1

        return blocks[:top_k]

    # ── 评分 ─────────────────────────────────────────────────────────────

    def _score(self, query_tokens: list[str], block: RankedContextBlock) -> float:
        """对单个块相对于查询 token 评分。"""
        block_tokens = self._tokenize(block.content)
        if not block_tokens:
            return 0.3

        # 基于 BM25 思路的词频评分
        score = 0.0
        for qt in query_tokens:
            tf = block_tokens.count(qt)
            if tf > 0:
                # 对数缩放的 TF
                score += 1.0 + min(tf, 3) * 0.5

        # 按块长度归一化（惩罚过长的块）
        length_penalty = min(1.0, 200 / max(len(block_tokens), 1))
        score *= length_penalty

        # 来源类型偏好：memory 和 data_source 默认略微更相关
        source_bias = {
            "memory": 1.2,
            "data_source": 1.1,
            "history": 1.0,
            "preferences": 0.9,
            "attachment": 1.1,
        }
        bias = source_bias.get(block.source_type, 1.0)
        score *= bias

        # 标题/关键词加分：查询词出现在块的前部
        early_content = block.content[:200].lower()
        for qt in query_tokens:
            if qt.lower() in early_content:
                score += 0.3

        # 归一化到 0-1 范围（类 sigmoid）
        normalized = score / (score + 3.0)
        return round(min(normalized, 0.99), 3)

    # ── 分词 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """简单多语言分词器 — 词语 + 中文二元组 + 字母数字。"""
        import re

        lowered = text.lower()
        tokens: list[str] = []

        # 字母数字 token（如 Q4、APIv2、2024Q4）
        alnum = re.findall(r'[a-z]+\d+[a-z]*|\d+[a-z]+', lowered)
        tokens.extend(alnum)

        # 英文单词（2+ 字符）
        en_words = re.findall(r'[a-z]{2,}', lowered)
        tokens.extend(en_words)

        # 中文字符（单字和二元组）
        cn_chars = re.findall(r'[一-鿿]+', lowered)
        for seq in cn_chars:
            tokens.append(seq)
            if len(seq) > 2:
                tokens.extend(seq[i:i+2] for i in range(len(seq)-1))

        # 独立数字
        numbers = re.findall(r'\d+', lowered)
        tokens.extend(numbers)

        return tokens
