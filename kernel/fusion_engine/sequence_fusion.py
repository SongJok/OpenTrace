"""序列融合引擎 — 多问场景下按子问题顺序融合各 Agent 结果。"""

from __future__ import annotations

from typing import Any

from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway
from .sequence_models import PerQuestionResult, SequenceFusionInput, SequenceFusionOutput


_IDENTITY_RE = r"(你是谁|你是什么|哪位|什么模型|什么助手|什么ai|哪家公司的|who\s+are\s+you|what\s+are\s+you|what\s+model)"
_IDENTITY_RESPONSE = (
    "我是 OpenTrace，一个基于认知内核（Cognitive Kernel）构建的 AI 系统。"
    "我支持数据库自然语言查询、文档检索、网页搜索、工具调用等多种能力，"
    "设计目标是安全、可解释、可编排。如果你对系统架构感兴趣，可以找Joony进行沟通"
)


class SequenceFusionEngine:
    async def run(self, input: SequenceFusionInput) -> SequenceFusionOutput:
        sub_questions = input.sub_questions or []
        agent_results = input.agent_results or []
        background_materials = input.background_materials or ""

        per_question_results: list[PerQuestionResult] = []
        gateway = get_model_gateway(LLMRole.QUERY)

        for idx, sq in enumerate(sub_questions):
            sub_question_id = sq.get("sub_question_id", f"sq_{idx}")
            text = sq.get("text", sq.get("question_text", ""))
            display_order = idx
            domain = sq.get("domain", "general_qa")

            result_refs: list[dict[str, Any]] = []
            success = True
            status = "ok"

            # Try to find matching agent result
            matching = [
                r
                for r in agent_results
                if self._guess_sub_question_id(r, sub_question_id) == sub_question_id
            ]

            if matching:
                answer = await self._generate_answer_for_question(
                    gateway, text, domain, matching[0], background_materials
                )
                source = matching[0].agent_type if hasattr(matching[0], "agent_type") else domain
                confidence = (
                    matching[0].confidence
                    if hasattr(matching[0], "confidence")
                    else 0.7
                )
            elif self._is_identity_question(text):
                answer = _IDENTITY_RESPONSE
                source = "identity"
                confidence = 0.95
            elif self._is_factual_question(text):
                answer = await self._generate_knowledge_answer(
                    gateway, text, background_materials
                )
                source = "knowledge"
                confidence = 0.5
            else:
                answer = "无法获取该部分信息（未找到相关结果）。"
                source = "error"
                confidence = 0.0
                success = False
                status = "no_results"

            per_question_results.append(
                PerQuestionResult(
                    sub_question_id=sub_question_id,
                    question_text=text,
                    display_order=display_order,
                    answer=answer,
                    success=success,
                    status=status,
                    source=source,
                    confidence=confidence,
                    result_refs=result_refs,
                )
            )

        content = self._assemble_content(per_question_results)
        avg_confidence = (
            sum(r.confidence for r in per_question_results) / max(len(per_question_results), 1)
        )
        all_refs: list[dict[str, Any]] = []
        for r in per_question_results:
            all_refs.extend(r.result_refs)

        return SequenceFusionOutput(
            content=content,
            per_question_results=per_question_results,
            confidence=avg_confidence,
            result_refs=all_refs,
        )

    @staticmethod
    def _guess_sub_question_id(result: Any, default: str) -> str:
        """Fallback: guess which sub-question a result belongs to."""
        if hasattr(result, "agent_type") and result.agent_type == "identity":
            return default
        return default

    @staticmethod
    def _is_identity_question(text: str) -> bool:
        import re

        return bool(re.search(_IDENTITY_RE, (text or "").strip(), re.IGNORECASE))

    @staticmethod
    def _is_factual_question(text: str) -> bool:
        keywords = ["什么是", "为什么", "如何", "怎么样", "who", "what", "why", "how"]
        return any(k in (text or "").lower() for k in keywords)

    async def _generate_answer_for_question(
        self,
        gateway: Any,
        query: str,
        domain: str,
        result: Any,
        background_materials: str,
    ) -> str:
        """Generate a natural-language answer for a single sub-question."""
        content = ""
        metadata_str = ""

        if hasattr(result, "content"):
            content = str(result.content)
        if hasattr(result, "data"):
            data = result.data
            row_count = data.get("row_count") or data.get("rowCount") or 0
            columns = data.get("columns", [])
            if row_count:
                content = f"[DATA row_count={row_count}]\n{content}"

        chunks = ""
        citations = ""
        if hasattr(result, "metadata") and result.metadata:
            if isinstance(result.metadata.get("chunks"), list):
                chunks = "\n".join(
                    f"  · [{c.get('title', c.get('source_name', ''))}] {c.get('snippet', '')}"
                    for c in result.metadata["chunks"][:5]
                )
                if chunks:
                    content = content or f"[RAG chunks={len(result.metadata['chunks'])}\n{chunks}"

        if hasattr(result, "source") and result.source == "web_search":
            content = content or "[WEB] 暂无可用信息。"

        # Build evidence prompt
        bg_part = ""
        if background_materials:
            bg_part = (
                "用户上传了以下文件作为背景材料，请将材料内容作为回答的知识背景：\n\n"
                "--- 背景材料开始 ---\n\n"
                f"{background_materials}\n\n"
                "--- 背景材料结束 ---\n\n"
            )

        if domain in ("sql", "data", "database", "table"):
            system_prompt = (
                "你是一个数据分析助手。根据数据库查询结果，用自然语言简洁地回答用户问题。"
                "先给出核心结论，再列出关键数据。如需展示表格数据，用 Markdown 表格格式。"
            )
        elif domain in ("document", "rag", "memory"):
            system_prompt = (
                "你是一个文档问答助手。根据检索到的文档证据，回答用户问题。"
                "先给结论，再引用相关文档内容。如果证据不足，坦诚说明。"
            )
        elif domain in ("web", "web_search", "search"):
            system_prompt = (
                "你是一个信息检索助手。根据搜索到的网络信息，简洁地回答用户问题。"
                "说明信息来源的时效性。"
            )
        else:
            system_prompt = (
                "你是一个精确的问答助手。根据提供的证据，简洁地回答用户的问题。"
                "用自然语言组织答案，保持简洁清晰。如果信息不足，请直接说明。"
            )

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(
                role="user",
                content=(
                    f"{bg_part}用户问题：{query}\n\n证据：{content}"
                ),
            ),
        ]

        try:
            resp = await gateway.chat(messages, temperature=0.7, max_tokens=1024)
            return str(resp) if resp else "抱歉，我暂时无法回答「" + query + "」"
        except Exception:
            meta = getattr(result, "metadata", {}) or {}
            error_msg = meta.get("error_reason", str(content))
            return f"执行出错" if not error_msg else error_msg

    async def _generate_knowledge_answer(
        self,
        gateway: Any,
        query: str,
        background_materials: str,
    ) -> str:
        """Answer a factual/trivia question from LLM knowledge."""
        bg_part = ""
        if background_materials:
            bg_part = (
                "用户上传了以下文件作为背景材料，请将材料内容作为回答的知识背景：\n\n"
                "--- 背景材料开始 ---\n\n"
                f"{background_materials}\n\n"
                "--- 背景材料结束 ---\n\n"
            )

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "你是一个知识问答助手。根据你自身的知识，简洁准确地回答用户的问题。\n"
                    "直接给出答案，不要编造不确定的信息。如果确实不知道，诚实说明。"
                ),
            ),
            LLMMessage(role="user", content=f"{bg_part}用户问题：{query}"),
        ]

        try:
            resp = await gateway.chat(messages, temperature=0.3, max_tokens=1024)
            return str(resp) if resp else "抱歉，我暂时无法回答「" + query + "」"
        except Exception:
            return "抱歉，我暂时无法回答「" + query + "」"

    @staticmethod
    def _assemble_content(results: list[PerQuestionResult]) -> str:
        """Assemble all sub-question answers into ordered Markdown with source badges."""
        results_sorted = sorted(results, key=lambda r: r.display_order)
        parts: list[str] = []
        for r in results_sorted:
            if r.status == "error" and not r.answer:
                continue
            if len(results_sorted) > 1:
                parts.append(f"\n### {r.question_text}\n\n{r.answer}")
            else:
                parts.append(r.answer)
        return "\n".join(parts).strip()
