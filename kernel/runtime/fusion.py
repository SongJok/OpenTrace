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

        from kernel.cognitive_controls import detect_response_format_hint, user_facing_query

        user_query = user_facing_query(
            getattr(ctx, "raw_user_query", "") or query
        ) or user_facing_query(query)
        format_hint = detect_response_format_hint(user_query)
        task_type = str(getattr(ctx, "task_type", "") or "")
        force_mode = str(getattr(ctx, "force_mode", "") or "")
        rag_turn = force_mode == "rag" or task_type in (
            "document_qa",
            "rag",
            "summarization",
        )

        # 在决定是否使用 LLM 融合前检测矛盾
        has_contradiction, contradiction_detail = self._detect_contradictions(success_evidence)

        use_llm = bool(self.llm_enabled) and (
            (has_contradiction and len(success_evidence) >= 2)
            or rag_turn
            or format_hint in ("one_sentence", "summary")
        )

        if use_llm:
            result = await self._llm_fuse(
                user_query,
                ctx,
                success_evidence,
                format_hint=format_hint,
                rag_turn=rag_turn,
            )
            if has_contradiction:
                result.contradictions = [contradiction_detail]
            return result

        result = self._heuristic_fuse(user_query, success_evidence)
        if has_contradiction:
            result.contradictions = [contradiction_detail]
        return result

    async def _llm_fuse(
        self,
        query: str,
        ctx: Any,
        evidence_list: list[Any],
        *,
        format_hint: str = "default",
        rag_turn: bool = False,
    ) -> FusionResult:
        """LLM 驱动的语义融合。"""
        deduped = self._dedupe_evidence_chunks(evidence_list)
        context_blocks: list[str] = []
        for i, ev in enumerate(deduped):
            source = getattr(ev.provenance, "source", "unknown")
            confidence = getattr(ev, "credibility_score", 0.5)
            body = (ev.content or "").strip()
            if not body:
                continue
            context_blocks.append(
                f"[片段{i+1} | 来源: {source} | 置信度: {confidence:.2f}]\n{body[:2000]}"
            )

        evidence_ids = [getattr(e, "evidence_id", "") for e in evidence_list]

        evidence_text = "\n\n---\n\n".join(context_blocks)

        if format_hint == "one_sentence":
            shape_rule = (
                "必须只用**一句**完整中文回答（可含分号，但不要分点、不要标题、不要复述政策条文）。"
                "先直接给出定义或结论，不要以「根据文档」开头。"
            )
            max_tokens = 256
        elif format_hint == "summary":
            shape_rule = (
                "用 3～6 条简短要点或一小段结构化总结作答；合并重复信息，不要大段粘贴原文。"
            )
            max_tokens = 800
        elif rag_turn:
            shape_rule = (
                "基于证据用自然语言直接回答用户问题；合并重复表述，不要逐段堆砌原文，"
                "不要输出「01-」类文档标题除非用户要求列条款。"
            )
            max_tokens = 1000
        else:
            shape_rule = "输出融合后的连贯回答（纯文本）。"
            max_tokens = 1200

        system_prompt = (
            "你是知识库问答助手，只根据给定证据作答。\n"
            "规则：\n"
            "1. 去重合并相似内容\n"
            "2. 不得编造证据中不存在的事实\n"
            "3. 若证据不足以回答，明确说明缺失项\n"
            f"4. 输出格式：{shape_rule}"
        )

        user_prompt = (
            f"## 用户问题\n{query}\n\n"
            f"## 检索到的证据\n{evidence_text}\n\n"
            "请直接输出最终答案（不要 markdown 代码块，不要「证据片段」字样）。"
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
                max_tokens=max_tokens,
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

    @staticmethod
    def _dedupe_evidence_chunks(evidence_list: list[Any]) -> list[Any]:
        """Drop near-duplicate chunks before LLM fusion (reduces messy paste)."""
        sorted_ev = sorted(
            evidence_list,
            key=lambda e: getattr(e, "credibility_score", 0.5),
            reverse=True,
        )
        seen: set[str] = set()
        out: list[Any] = []
        for ev in sorted_ev:
            body = (getattr(ev, "content", "") or "").strip()
            if not body:
                continue
            key = body[:200]
            if key in seen:
                continue
            seen.add(key)
            out.append(ev)
        return out[:8]

    def _heuristic_fuse(self, query: str, evidence_list: list[Any]) -> FusionResult:
        """简单优先级合并：最高置信度优先，拼接内容。"""
        sorted_ev = self._dedupe_evidence_chunks(evidence_list)

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
