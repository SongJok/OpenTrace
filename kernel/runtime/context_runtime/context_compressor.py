"""
上下文压缩器 — 对 LLM 提示词中的上下文块进行语义压缩。

用 token 感知、语义感知的压缩替代简单的 [:N] 截断。
保留关键信息，丢弃冗余、无关或低价值内容。

策略（无需 LLM）：
1. 计算 token 数（通过字符比率近似）
2. 识别高价值句子（命名实体、数字、关键术语）
3. 优先丢弃低价值句子
4. 如果仍超出预算，应用抽取式摘要
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CompressedBlock:
    """压缩后的上下文块，可直接插入提示词。"""
    content: str
    original_length: int
    compressed_length: int
    compression_ratio: float
    quality_score: float  # 0-1，关键信息保留程度
    dropped_sentences: list[str] = field(default_factory=list)


class ContextCompressor:
    """token 感知的语义压缩。

    将上下文块压缩到 token 预算内，同时最大化信息密度。
    使用抽取式摘要启发式方法 — 无需 LLM 调用。
    """

    # 近似：1 token ≈ 2.5 个中文字符，4 个英文字符
    CHARS_PER_TOKEN_CN = 2.5
    CHARS_PER_TOKEN_EN = 4.0

    def __init__(self, max_tokens: int = 800) -> None:
        self.max_tokens = max_tokens

    def compress(self, text: str, source_label: str = "") -> CompressedBlock:
        """将文本压缩到 max_tokens 预算内。

        Args:
            text: 需要压缩的原始上下文文本。
            source_label: 用于日志的标签（如 "memory"、"history"、"preferences"）。

        Returns:
            包含压缩内容和质量指标的 CompressedBlock。
        """
        original_len = len(text)
        if not text.strip():
            return CompressedBlock(
                content="",
                original_length=0,
                compressed_length=0,
                compression_ratio=1.0,
                quality_score=1.0,
            )

        # 快速路径：已在预算内
        estimated_tokens = self._estimate_tokens(text)
        if estimated_tokens <= self.max_tokens:
            return CompressedBlock(
                content=text,
                original_length=original_len,
                compressed_length=original_len,
                compression_ratio=1.0,
                quality_score=1.0,
            )

        # 慢速路径：需要压缩
        max_chars = int(self.max_tokens * self.CHARS_PER_TOKEN_CN)

        # 按句子拆分（支持中文：按 。！？. ! ? \n 分割）
        sentences = self._split_sentences(text)
        if len(sentences) <= 1:
            # 单一块 — 硬截断
            truncated = text[:max_chars]
            return CompressedBlock(
                content=truncated,
                original_length=original_len,
                compressed_length=len(truncated),
                compression_ratio=len(truncated) / max(original_len, 1),
                quality_score=0.7,
            )

        # 按信息密度对每个句子评分
        scored = self._score_sentences(sentences)

        # 贪心选择：取最高评分的句子直到预算用尽
        scored.sort(key=lambda x: x[1], reverse=True)
        selected: list[str] = []
        selected_chars = 0
        dropped: list[str] = []

        for sent, score in scored:
            if selected_chars + len(sent) <= max_chars:
                selected.append(sent)
                selected_chars += len(sent)
            else:
                dropped.append(sent)

        # 按原始位置重排
        original_order = {s: i for i, s in enumerate(sentences)}
        selected.sort(key=lambda s: original_order.get(s, 9999))

        compressed = "".join(selected)
        quality = self._estimate_quality(selected, dropped, text)

        logger.debug(
            "ContextCompressor",
            source=source_label,
            original_len=original_len,
            compressed_len=len(compressed),
            sentences_before=len(sentences),
            sentences_after=len(selected),
            quality=round(quality, 2),
        )

        return CompressedBlock(
            content=compressed,
            original_length=original_len,
            compressed_length=len(compressed),
            compression_ratio=len(compressed) / max(original_len, 1),
            quality_score=quality,
            dropped_sentences=dropped[:5],
        )

    # ── 辅助方法 ────────────────────────────────────────────────────────────

    def _estimate_tokens(self, text: str) -> int:
        cn_chars = sum(1 for c in text if '一' <= c <= '鿿')
        en_chars = len(text) - cn_chars
        return int(cn_chars / self.CHARS_PER_TOKEN_CN + en_chars / self.CHARS_PER_TOKEN_EN)

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """将文本拆分为句子，支持中文。"""
        import re
        # 按中英文句子边界分割
        parts = re.split(r'(?<=[。！？.!?\n])\s*', text)
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def _score_sentences(sentences: list[str]) -> list[tuple[str, float]]:
        """按信息密度对句子评分。"""
        import re

        scored: list[tuple[str, float]] = []
        for sent in sentences:
            score = 1.0

            # 加分：命名实体（英文大写词、2+ 字中文名词）
            if re.search(r'[A-Z][a-z]{2,}', sent):
                score += 1.0

            # 加分：数字/百分比/日期
            if re.search(r'\d+', sent):
                score += 0.8

            # 加分：关键指示词
            key_terms = ['关键', '重要', '必须', '核心', '主要', '结论', '结果',
                         'critical', 'important', 'must', 'key', 'core', 'result']
            for term in key_terms:
                if term in sent.lower():
                    score += 0.5
                    break

            # 减分：极短句子（通常是连接词）
            if len(sent) < 10:
                score -= 0.5

            # 减分：填充短语
            filler = ['另外', '顺便', '补充', '备注', 'note:', 'ps:', 'btw']
            for f in filler:
                if f in sent.lower():
                    score -= 0.3
                    break

            scored.append((sent, max(score, 0.1)))

        return scored

    @staticmethod
    def _estimate_quality(
        selected: list[str], dropped: list[str], original: str
    ) -> float:
        """压缩结果相对于原文的启发式质量评估。"""
        if not dropped:
            return 1.0

        # 质量 = 保留的关键信息比例
        # 关键信息 = 包含实体、数字、关键术语的句子
        import re

        def _has_key_info(s: str) -> bool:
            return bool(
                re.search(r'[A-Z][a-z]{2,}', s)
                or re.search(r'\d{2,}', s)
                or any(t in s.lower() for t in ['关键', '重要', '必须', '核心', '结果', '结论'])
            )

        key_dropped = sum(1 for d in dropped if _has_key_info(d))
        key_total = sum(1 for s in selected + dropped if _has_key_info(s)) or 1

        return max(0.3, 1.0 - (key_dropped / key_total))
