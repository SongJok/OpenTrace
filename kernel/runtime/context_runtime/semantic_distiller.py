"""
语义蒸馏器 — 将上下文块蒸馏为紧凑的高密度摘要。

当上下文块即使经过压缩仍然过大时，蒸馏器生成保留
最关键信息的结构化摘要。

仅在必要时使用 CHEAP_CRITIC LLM 调用；否则使用启发式回退。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DistilledContext:
    """最终蒸馏后的上下文，可直接注入提示词。"""
    summary: str = ""
    key_facts: list[str] = field(default_factory=list)
    key_entities: list[str] = field(default_factory=list)
    original_total_chars: int = 0
    distilled_chars: int = 0
    method: str = "heuristic"  # heuristic | llm


class SemanticDistiller:
    """将多个上下文块蒸馏为单个紧凑摘要。

    启发式路径：按实体/数字密度提取关键句子。
    LLM 路径（可选）：一次 CHEAP_CRITIC 调用进行语义摘要。
    """

    def __init__(self, use_llm: bool = False) -> None:
        self.use_llm = use_llm

    async def distill(
        self,
        query: str,
        blocks: list[Any],  # list[RankedContextBlock]
        max_chars: int = 1200,
    ) -> DistilledContext:
        """将排序后的上下文块蒸馏为紧凑摘要。

        Args:
            query: 用于相关性引导的用户查询。
            blocks: 排序后的上下文块（已按相关性排序）。
            max_chars: 蒸馏输出的最大字符数。

        Returns:
            包含摘要和提取的关键事实/实体的 DistilledContext。
        """
        if not blocks:
            return DistilledContext()

        original_total = sum(len(b.content) for b in blocks)

        # 快速路径：总量已经很小
        if original_total <= max_chars:
            combined = "\n".join(b.content for b in blocks)
            return DistilledContext(
                summary=combined,
                original_total_chars=original_total,
                distilled_chars=original_total,
                method="passthrough",
            )

        # LLM 路径
        if self.use_llm and original_total > max_chars * 2:
            try:
                return await self._llm_distill(query, blocks, max_chars)
            except Exception as exc:
                logger.debug("semantic_distiller_llm_skipped", error=str(exc))

        # 启发式路径
        return self._heuristic_distill(query, blocks, max_chars)

    async def _llm_distill(
        self, query: str, blocks: list[Any], max_chars: int
    ) -> DistilledContext:
        """LLM 驱动的语义蒸馏（CHEAP_CRITIC 角色）。"""
        combined = "\n\n---\n\n".join(
            f"[{b.source_type}]\n{b.content[:800]}" for b in blocks[:5]
        )

        system_prompt = (
            "你是上下文蒸馏专家。将多个上下文块压缩为紧凑摘要，保留与用户查询最相关的信息。\n"
            "输出 JSON 格式：{\"summary\": \"...\", \"key_facts\": [\"...\"], \"key_entities\": [\"...\"]}"
        )
        user_prompt = (
            f"## 用户查询\n{query}\n\n"
            f"## 上下文块\n{combined}\n\n"
            f"请蒸馏为不超过 {max_chars} 字符的摘要。"
        )

        import json

        from model.model_gateway.gateway import LLMMessage, LLMRole, get_model_gateway

        gw = get_model_gateway()
        resp = await gw.complete(
            [
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_prompt),
            ],
            role=LLMRole.CHEAP_CRITIC,
            temperature=0.0,
            max_tokens=400,
        )
        text = (resp.content or "").strip()

        try:
            text_clean = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(text_clean)
        except json.JSONDecodeError:
            return self._heuristic_distill(query, blocks, max_chars)

        summary = str(data.get("summary", ""))[:max_chars]
        return DistilledContext(
            summary=summary,
            key_facts=list(data.get("key_facts", []) or []),
            key_entities=list(data.get("key_entities", []) or []),
            original_total_chars=sum(len(b.content) for b in blocks),
            distilled_chars=len(summary),
            method="llm",
        )

    def _heuristic_distill(
        self, query: str, blocks: list[Any], max_chars: int
    ) -> DistilledContext:
        """抽取式蒸馏：从最高排名的块中取最高评分的句子。"""
        import re

        all_sentences: list[tuple[str, float]] = []
        for block in blocks[:5]:
            base_score = getattr(block, "relevance_score", 0.5)
            sentences = self._split_sentences(getattr(block, "content", ""))
            for sent in sentences:
                # 按实体/数字密度 + 块相关性对句子评分
                sent_score = base_score
                if re.search(r'[A-Z][a-z]{2,}', sent):
                    sent_score += 0.3
                if re.search(r'\d+', sent):
                    sent_score += 0.2
                all_sentences.append((sent, sent_score))

        all_sentences.sort(key=lambda x: x[1], reverse=True)

        selected: list[str] = []
        chars = 0
        for sent, _ in all_sentences:
            if chars + len(sent) <= max_chars:
                selected.append(sent)
                chars += len(sent)
            if chars >= max_chars:
                break

        summary = " ".join(selected)

        # 提取关键事实（包含数字或命名实体的句子）
        key_facts: list[str] = []
        for sent, _ in all_sentences[:8]:
            if re.search(r'\d{2,}', sent) or re.search(r'[A-Z][a-z]{3,}', sent):
                key_facts.append(sent[:150])
            if len(key_facts) >= 5:
                break

        # 提取关键实体（大写词、长中文名词）
        key_entities: list[str] = []
        for block in blocks[:3]:
            content = getattr(block, "content", "")
            # 中文实体：2-4 字符序列
            cn_entities = re.findall(r'[一-鿿]{2,4}', content)
            key_entities.extend(cn_entities[:5])
            # 英文实体：大写词
            en_entities = re.findall(r'[A-Z][a-z]{3,}', content)
            key_entities.extend(en_entities[:5])
        key_entities = list(dict.fromkeys(key_entities))[:10]

        original_total = sum(len(getattr(b, "content", "")) for b in blocks)

        return DistilledContext(
            summary=summary[:max_chars],
            key_facts=key_facts,
            key_entities=key_entities,
            original_total_chars=original_total,
            distilled_chars=len(summary),
            method="heuristic",
        )

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        import re
        parts = re.split(r'(?<=[。！？.!?\n])\s*', text)
        return [p.strip() for p in parts if p.strip() and len(p.strip()) > 5]
