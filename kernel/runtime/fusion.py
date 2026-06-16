"""
FusionEngineV2 — 使用 LLM（QUERY 角色）的语义证据融合。

用 LLM 驱动的语义融合取代基于启发式权重的 FusionEngine，
实现去重、矛盾检测、带置信度的合并以及不确定性表达。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)


class FusionEngineV2:
    """LLM 驱动的证据融合。

    简单/FAQ 查询走快速路径（启发式）。
    复杂多源证据走 LLM 路径（QUERY 角色）。
    """

    def __init__(self) -> None:
        self._llm_enabled: bool | None = None

    @property
    def llm_enabled(self) -> bool:
        if self._llm_enabled is None:
            self._llm_enabled = bool(getattr(settings, "kernel_fusion_v2_enabled", False))
        return self._llm_enabled

    async def fuse(
        self,
        query: str,
        ctx: Any,  # RuntimeContext
        evidence_list: list[Any],  # list[Evidence]
    ) -> FusionResult:
        """将证据融合为连贯的回答。

        默认：确定性启发式融合（不调用 LLM）。
        仅当检测到跨源矛盾时才使用 LLM 融合。
        """
        if not evidence_list:
            return FusionResult(
                merged_context="",
                confidence=0.0,
                method="empty",
            )

        success_evidence = [e for e in evidence_list if getattr(e, "credibility_score", 0) > 0]
        if not success_evidence:
            errors = [f"{e.provenance.source}: {e.content[:200]}" for e in evidence_list]
            return FusionResult(
                merged_context="\n".join(errors),
                confidence=0.0,
                method="error_aggregation",
            )

        # 在决定是否使用 LLM 融合前检测矛盾
        has_contradiction, contradiction_detail = self._detect_contradictions(success_evidence)

        if self.llm_enabled and has_contradiction and len(evidence_list) >= 2:
            return await self._llm_fuse(query, ctx, success_evidence)

        result = self._heuristic_fuse(query, success_evidence)
        if has_contradiction:
            result.contradictions = [contradiction_detail]
        return result

    async def _llm_fuse(
        self,
        query: str,
        ctx: Any,
        evidence_list: list[Any],
    ) -> FusionResult:
        """LLM 驱动的语义融合。"""
        context_blocks: list[str] = []
        for i, ev in enumerate(evidence_list):
            source = getattr(ev.provenance, "source", "unknown")
            confidence = getattr(ev, "credibility_score", 0.5)
            context_blocks.append(
                f"[来源{i+1}: {source} | 置信度: {confidence:.2f}]\n{ev.content[:1500]}"
            )

        evidence_ids = [getattr(e, "evidence_id", "") for e in evidence_list]

        evidence_text = "\n\n---\n\n".join(context_blocks)

        system_prompt = (
            "你是证据融合专家。将多个来源的查询结果融合为连贯的回答。\n"
            "规则：\n"
            "1. 去重：语义相似的表述合并，保留置信度最高的\n"
            "2. 矛盾检测：如果两个来源给出不同答案，明确指出差异\n"
            "3. 置信度表达：对不确定的信息使用「可能」「据现有信息」等措辞\n"
            "4. 优先使用置信度高的来源\n"
            "5. 保持客观，不编造信息"
        )

        user_prompt = (
            f"## 用户提问\n{query}\n\n"
            f"## 各来源证据\n{evidence_text}\n\n"
            "请输出融合后的回答（纯文本，不含 markdown 标记）。"
        )

        try:
            from model.model_gateway.gateway import LLMMessage, LLMRole, get_model_gateway

            gw = get_model_gateway()
            resp = await gw.complete(
                [
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=user_prompt),
                ],
                role=LLMRole.QUERY,
                temperature=0.1,
                max_tokens=1200,
            )
            return FusionResult(
                merged_context=(resp.content or "").strip(),
                confidence=self._avg_confidence(evidence_list),
                method="llm_fusion_v2",
                evidence_ids=evidence_ids,
            )
        except Exception as exc:
            logger.warning("FusionV2 LLM call failed, falling back to heuristic", error=str(exc))
            return self._heuristic_fuse(query, evidence_list)

    def _heuristic_fuse(self, query: str, evidence_list: list[Any]) -> FusionResult:
        """简单优先级合并：最高置信度优先，拼接内容。"""
        sorted_ev = sorted(
            evidence_list,
            key=lambda e: getattr(e, "credibility_score", 0.5),
            reverse=True,
        )

        parts: list[str] = []
        for ev in sorted_ev:
            content = (ev.content or "").strip()
            if content:
                parts.append(content)

        merged = "\n\n".join(parts)
        return FusionResult(
            merged_context=merged,
            confidence=self._avg_confidence(evidence_list),
            method="heuristic_v2",
            evidence_ids=[getattr(e, "evidence_id", "") for e in evidence_list],
        )

    def _detect_contradictions(self, evidence_list: list[Any]) -> tuple[bool, str]:
        """跨证据源的确定性矛盾检测。

        返回 (是否存在矛盾, 详情)。
        """
        if len(evidence_list) < 2:
            return False, ""

        sources = [getattr(e.provenance, "source", "unknown") for e in evidence_list]
        # 同一来源 → 无矛盾
        if len(set(sources)) <= 1:
            return False, ""

        # 检查数值矛盾：如果两个来源对同一主题报告了显著不同的数值
        contents = [(getattr(e, "content", "") or "") for e in evidence_list]
        import re
        nums: list[list[float]] = []
        for c in contents:
            found = re.findall(r"[\d,.]+", c)
            nums.append([float(f.replace(",", "")) for f in found if f.replace(",", "").replace(".", "").isdigit()])

        # 比较跨来源的数值
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                for ni in nums[i]:
                    for nj in nums[j]:
                        if ni > 0 and nj > 0:
                            ratio = max(ni, nj) / min(ni, nj)
                            if ratio > 2.0:
                                return True, (
                                    f"Contradiction: {sources[i]} reports {ni:.1f}, "
                                    f"{sources[j]} reports {nj:.1f} (ratio {ratio:.1f}x)"
                                )

        # 检查关键词矛盾
        contradict_keywords = [
            ("增加", "下降"), ("增长", "减少"), ("上升", "下跌"),
            ("increased", "decreased"), ("grew", "declined"),
            ("yes", "no"), ("是", "否"), ("true", "false"),
        ]
        for kw_a, kw_b in contradict_keywords:
            for i in range(len(contents)):
                for j in range(i + 1, len(contents)):
                    if kw_a in contents[i].lower() and kw_b in contents[j].lower():
                        return True, f"Contradiction: {sources[i]} says '{kw_a}', {sources[j]} says '{kw_b}'"

        return False, ""

    @staticmethod
    def _avg_confidence(evidence_list: list[Any]) -> float:
        if not evidence_list:
            return 0.0
        return sum(getattr(e, "credibility_score", 0.5) for e in evidence_list) / len(evidence_list)


class FusionResult:
    """融合过程的输出。"""

    def __init__(
        self,
        merged_context: str,
        confidence: float = 0.0,
        contradictions: list[str] | None = None,
        method: str = "",
        evidence_ids: list[str] | None = None,
    ) -> None:
        self.merged_context = merged_context
        self.confidence = confidence
        self.contradictions = contradictions or []
        self.method = method
        self.evidence_ids = evidence_ids or []
