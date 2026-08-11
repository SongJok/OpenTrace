"""
UnderstandingEngine — Deep cognitive understanding beyond intent classification.

Outputs a structured UnderstandingResult with: explicit goal, hidden goal,
entities, constraints, ambiguity assessment, risk level, expected output type,
required capabilities, execution strategy, and completion criteria.

This is NOT intent classification. This is true task comprehension.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kernel.runtime.context import RuntimeContext
    from kernel.runtime.objects import RuntimeCanonicalQuery, UnderstandingResult

from infra.observability.logger import get_logger

logger = get_logger(__name__)

# Heuristic fast path: queries matching these patterns are "simple"
_SIMPLE_PATTERNS = [
    r"^(你好|hi|hello|嘿|嗨)[\s!！。.,，]*$",
    r"^(谢谢|thank|thanks|3Q|thx)[\s!！。.,，]*$",
    r"^(再见|bye|拜拜|88)[\s!！。.,，]*$",
    r"^(帮助|help|帮帮我)[\s!！。.,，]*$",
    r"(你能做什么|你可以做什么|怎么帮我|你有哪些?功能|你的能力)",
]


class UnderstandingEngine:
    """Deep cognitive understanding — one LLM call for task comprehension.

    Input:  RuntimeCanonicalQuery (already rewritten with full context)
    Output: UnderstandingResult (structured task understanding)
    """

    def __init__(self) -> None:
        pass

    async def understand(
        self,
        canonical: RuntimeCanonicalQuery,
        ctx: RuntimeContext,
    ) -> UnderstandingResult:
        """Produce a structured understanding of the canonical query.

        Fast path: trivially simple queries → heuristic result.
        LLM path: normal queries → one LLM call for deep understanding.
        """
        from kernel.runtime.objects import UnderstandingResult

        query = canonical.canonical_query

        # ── Fast path: trivially simple queries ──
        for pattern in _SIMPLE_PATTERNS:
            if re.match(pattern, query):
                logger.debug("UnderstandingEngine fast path — simple greeting/politeness")
                return UnderstandingResult(
                    raw_query=canonical.original_query,
                    normalized_query=query,
                    protected_intent=canonical.protected_intent or query,
                    planning_hints=["direct_answer"],
                    intent_confidence=0.96,
                    explicit_goal=query,
                    hidden_goal="",
                    ambiguity="none",
                    risk_level="low",
                    expected_output_type="text",
                    required_capabilities=[],
                    execution_strategy="direct",
                    completion_criteria="简短礼貌回复",
                    domain="conversation",
                )

        # ── LLM path: deep cognitive understanding ──
        try:
            return await self._understand_via_llm(query, ctx)
        except Exception as exc:
            logger.error("UnderstandingEngine LLM call failed", error=str(exc))
            return UnderstandingResult(
                raw_query=canonical.original_query,
                normalized_query=query,
                protected_intent=canonical.protected_intent or query,
                intent_confidence=0.4,
                explicit_goal=query,
                hidden_goal="",
                ambiguity="unknown",
                risk_level="low",
                expected_output_type="text",
                required_capabilities=[],
                execution_strategy="direct",
                completion_criteria="",
                domain="",
            )

    # ── LLM-based understanding ────────────────────────────────────────────

    async def _understand_via_llm(
        self, query: str, ctx: RuntimeContext
    ) -> UnderstandingResult:
        from kernel.runtime.objects import UnderstandingResult

        from model.model_gateway.gateway import LLMMessage, LLMRole, get_model_gateway

        system_prompt = self._build_system_prompt(ctx)
        user_prompt = f"## 规范化的用户查询\n{query}"

        gw = get_model_gateway()
        resp = await gw.complete(
            [
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_prompt),
            ],
            role=LLMRole.QUERY,
            temperature=0.0,
            max_tokens=800,
        )
        text = (resp.content or "").strip()

        return self._parse_understanding_result(text, query)

    def _build_system_prompt(self, ctx: RuntimeContext) -> str:
        ds_info = ""
        if ctx.data_source_context and ctx.data_source_context.get("data_source_id"):
            ds = ctx.data_source_context
            ds_info = (
                f"- 已绑定数据源: {ds.get('data_source_name', '')} "
                f"(type={ds.get('source_type', '')}, db={ds.get('database', '')})"
            )

        capability_list = self._get_capability_list()

        return f"""你是 Cognitive Understanding Engine。你的任务是深度理解用户查询——不是简单的意图分类，而是真正的任务认知。

## 你需要分析
1. **explicit_goal**: 用户明确说了什么？（一句话）
2. **hidden_goal**: 用户隐含的需求是什么？（可能为空）
3. **entities**: 涉及的实体列表 [{{"name": "华东区", "type": "region"}}, ...]
4. **constraints**: 约束条件（时间范围、数据范围、输出格式等）
5. **ambiguity**: 查询中的歧义点（如果有）
6. **risk_level**: low|medium|high — 查询可能涉及的风险级别
7. **expected_output_type**: text|table|chart|code|report — 预期的输出类型
8. **required_capabilities**: 需要的执行能力 ["data.query", "web.search", "rag.retrieve", "tool.datetime", "python.execute", ...]
9. **execution_strategy**: direct|parallel|sequential|compare — 执行策略
10. **completion_criteria**: 什么算任务完成？（一句话）
11. **domain**: 查询所属领域（finance|sales|hr|engineering|general|...）

{capability_list}

## 上下文
{ds_info}

## 输出格式（纯 JSON，无 markdown 包裹）
{{
  "explicit_goal": "用户明确想要什么",
  "hidden_goal": "隐含需求（没有则为空字符串）",
  "entities": [{{"name": "", "type": ""}}],
  "constraints": ["约束1", "约束2"],
  "ambiguity": "歧义描述（没有则为空字符串）",
  "risk_level": "low|medium|high",
  "expected_output_type": "text|table|chart|code|report",
  "required_capabilities": ["capability.type"],
  "execution_strategy": "direct|parallel|sequential|compare",
  "completion_criteria": "完成标准",
  "domain": "领域"
}}"""

    def _get_capability_list(self) -> str:
        """Build the capability list for the system prompt — dynamic or hardcoded fallback."""
        try:
            from kernel.capability_intelligence import (
                _capability_intelligence_enabled,
                capability_profiler,
                CapabilityAdapter,
            )
            from kernel.runtime.capability import capability_registry

            if _capability_intelligence_enabled():
                capability_profiler.build_profiles(capability_registry)
                profiles = capability_profiler.list_profiles()
                if profiles:
                    adapter = CapabilityAdapter()
                    return "## 可用的能力类型\n" + adapter.format_for_understanding_engine(profiles)
        except Exception as exc:
            logger.debug("understanding_engine_capability_profiles_skipped", error=str(exc))

        # Hardcoded fallback (backward compatible)
        return """## 可用的能力类型
- data.query: 结构化数据查询（SQL/DataAgent）
- data.analysis: 数据分析/统计/趋势
- web.search: 联网搜索实时信息
- rag.retrieve: 文档/知识库检索
- tool.datetime: 日期时间查询
- tool.weather: 天气查询
- tool.calculator: 数值计算
- python.execute: 代码执行/数据处理
- chart.generate: 图表生成
- memory.retrieve: 历史记忆检索
- entity.resolution: 命名实体消歧"""

    def _parse_understanding_result(self, text: str, fallback_query: str) -> UnderstandingResult:
        from kernel.runtime.objects import UnderstandingResult

        text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        text = re.sub(r"\n?\s*```\s*$", "", text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("UnderstandingEngine JSON parse failed", raw=text[:200])
            return UnderstandingResult(
                raw_query=fallback_query,
                normalized_query=fallback_query,
                protected_intent=fallback_query,
                intent_confidence=0.3,
                explicit_goal=fallback_query,
                risk_level="low",
                expected_output_type="text",
            )

        return UnderstandingResult(
            raw_query=fallback_query,
            normalized_query=str(data.get("explicit_goal", fallback_query)),
            protected_intent=fallback_query,
            planning_hints=list(data.get("planning_hints", []) or []),
            expanded_context=list(data.get("expanded_context", []) or []),
            intent_confidence=float(data.get("intent_confidence", 0.7) or 0.7),
            explicit_goal=str(data.get("explicit_goal", fallback_query)),
            hidden_goal=str(data.get("hidden_goal", "")),
            entities=list(data.get("entities", []) or []),
            constraints=list(data.get("constraints", []) or []),
            ambiguity=str(data.get("ambiguity", "")),
            risk_level=str(data.get("risk_level", "low")),
            expected_output_type=str(data.get("expected_output_type", "text")),
            required_capabilities=list(data.get("required_capabilities", []) or []),
            execution_strategy=str(data.get("execution_strategy", "direct")),
            completion_criteria=str(data.get("completion_criteria", "")),
            domain=str(data.get("domain", "")),
        )
