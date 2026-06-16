"""澄清门 — 检测模糊查询并生成反问。

两类：
- ClarificationGate：对话编排器原桩（向后兼容）
- DataClarificationGate：DataAgent V2 流水线活跃门
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field


# ── 共享类型 ────────────────────────────────────────────────────────────

@dataclass
class ClarificationQuestion:
    """结构化澄清问题，用于前端渲染。"""
    question_id: str = ""
    question_text: str = ""
    missing_entities: list[str] = field(default_factory=list)
    suggested_options: list[str] = field(default_factory=list)


@dataclass
class ClarificationResult:
    needs_clarification: bool = False
    clarification_question: str = ""
    question: ClarificationQuestion | None = None


# ── 原始桩（保留用于对话编排器兼容性） ────────────

class ClarificationGate:
    """原始桩 — 保留用于对话编排器向后兼容。"""

    async def check(
        self,
        fusion_confidence: float = 0.0,
        answer: str = "",
        query: str = "",
    ) -> ClarificationResult:
        return ClarificationResult()


# ── DataAgent V2 活跃门 ─────────────────────────────────────────────

# 表示查询过于模糊、无法确定性回答的模式
_GENERIC_PATTERNS = [
    re.compile(p)
    for p in [
        r"查一下数据",
        r"看看数据",
        r"帮我查",
        r"帮我看看",
        r"最近情况",
        r"最近怎么样",
        r"有什么数据",
        r"数据分析",
        r"分析一下",
        r"查点东西",
        r"帮我找",
        r"搜一下",
        r"查询一下",
        r"有没有.*数据",
        r"帮我分析",
    ]
]


class DataClarificationGate:
    """检测模糊的数据查询并生成有用的反问。

    检测采用纯信号逻辑（不调用 LLM）。问题生成使用
    LLM（PLANNING 角色）来生成自然、感知 schema 的反问。
    """

    def detect(self, ctx) -> dict:
        """对认知上下文执行纯信号模糊检测。

        返回包含信号标志和总体 needs_clarification 布尔值的字典。
        此处不进行 LLM 调用。

        Args:
            ctx: 来自 agents.data_agent_v2.types 的 CognitiveContext
        """
        entities = ctx.entities or []
        metrics = ctx.metrics or []
        intent = ctx.intent or {}
        intent_type = intent.get("intent_type", "") if isinstance(intent, dict) else ""
        intent_confidence = intent.get("confidence", 0.0) if isinstance(intent, dict) else 0.0

        # ── 信号提取 ────────────────────────────────────────────
        no_entities = not entities or all(
            not (e.get("mapped_table") if isinstance(e, dict) else False)
            for e in entities
        )
        no_metrics = not metrics or all(
            not (m.get("mapped_column") if isinstance(m, dict) else False)
            for m in metrics
        )
        low_intent_confidence = intent_confidence <= 0.55
        raw_lookup_intent = intent_type == "raw_lookup"
        is_analytical = intent_type in {
            "aggregation", "ranking", "distribution", "composition",
            "comparison", "trend", "anomaly_detection",
        }
        dimensions = intent.get("dimensions", []) if isinstance(intent, dict) else []
        empty_dimensions = is_analytical and (not dimensions)

        # 过短：去除空白和常见标点
        q_clean = re.sub(
            r"[\s.,;:!?，。；：！？、""'']+",
            "",
            ctx.query or "",
        )
        too_short = len(q_clean) <= 6

        # 通用模式匹配
        query_text = ctx.query or ""
        generic_pattern = any(p.search(query_text) for p in _GENERIC_PATTERNS)

        # ── 组合规则（先特殊后一般） ───────────────────
        signals = {
            "no_entities": no_entities,
            "no_metrics": no_metrics,
            "low_intent_confidence": low_intent_confidence,
            "raw_lookup_intent": raw_lookup_intent,
            "empty_dimensions": empty_dimensions,
            "too_short": too_short,
            "generic_pattern": generic_pattern,
        }

        # 规则1：无实体且分析意图无维度
        # （例如"统计分布"但未指明哪个表）
        if no_entities and empty_dimensions:
            return {**signals, "needs_clarification": True, "reason": "analytical_no_table_no_dims"}

        # 规则2：无实体且无指标 → 需要澄清
        if no_entities and no_metrics:
            return {**signals, "needs_clarification": True, "reason": "no_entities_and_no_metrics"}

        # 规则3：无实体且匹配通用模式 → 澄清
        if no_entities and generic_pattern:
            return {**signals, "needs_clarification": True, "reason": "no_entities_and_generic"}

        # 规则4：低置信度且原始查询 → 澄清
        if low_intent_confidence and raw_lookup_intent:
            return {**signals, "needs_clarification": True, "reason": "low_confidence_raw_lookup"}

        # 规则5：过短且无实体 → 澄清
        if too_short and no_entities:
            return {**signals, "needs_clarification": True, "reason": "too_short_no_entities"}

        return {**signals, "needs_clarification": False, "reason": ""}

    async def generate_question(
        self,
        query: str,
        detect_result: dict,
        ctx,
    ) -> ClarificationQuestion:
        """通过 LLM 生成自然语言澄清问题。

        Args:
            query: 原始用户查询
            detect_result: detect() 的输出，包含信号标志和原因
            ctx: 包含 schema 信息的 CognitiveContext

        Returns:
            包含 question_text 和 suggested_options 的 ClarificationQuestion
        """
        # 为 LLM 构建简洁的 schema 摘要
        schema_summary = self._build_schema_summary(ctx)

        prompt = self._build_generation_prompt(query, detect_result, schema_summary)
        enrich = getattr(ctx, "clarification_enrichment_block", "") or ""
        if enrich:
            prompt = f"{prompt}\n\n{enrich[:2000]}"

        try:
            from model.model_gateway.gateway import LLMRole, get_model_gateway
            from model.llm_adapter.base import LLMMessage

            gw = get_model_gateway()
            response = await gw.chat(
                messages=[
                    LLMMessage(role="system", content=CLARIFICATION_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=prompt),
                ],
                role=LLMRole.PLANNING,
                temperature=0.3,
                max_tokens=400,
            )

            import json
            data = json.loads(response.content.strip())

            return ClarificationQuestion(
                question_id=str(uuid.uuid4()),
                question_text=data.get("question_text", ""),
                missing_entities=data.get("missing_entities", []),
                suggested_options=data.get("suggested_options", []),
            )
        except Exception:
            # 降级：构建基于规则的澄清问题
            return self._fallback_question(query, detect_result, ctx)

    # ── 辅助方法 ──────────────────────────────────────────────────────────

    def _build_schema_summary(self, ctx) -> str:
        """为 LLM 上下文构建简洁的表/列摘要。

        包含表名和关键列，以便 LLM 能生成使用真实表名/列名的
        具体、可执行的建议选项。
        """
        parts = []
        tables = ctx.table_names or []
        table_columns = ctx.table_columns or {}

        if tables:
            lines = ["可用数据表："]
            for t in tables[:8]:
                cols = table_columns.get(t, [])
                col_preview = ", ".join(cols[:6])
                if col_preview:
                    lines.append(f"  • {t}（字段：{col_preview}）")
                else:
                    lines.append(f"  • {t}")
            parts.append("\n".join(lines))

        if not tables:
            parts.append("暂无可用表的 schema 信息。")

        return "\n".join(parts)

    def _build_generation_prompt(
        self, query: str, detect_result: dict, schema_summary: str
    ) -> str:
        reason = detect_result.get("reason", "")
        reason_labels = {
            "no_entities_and_no_metrics": "无法从提问中识别出任何表名、字段名或指标名称",
            "no_entities_and_generic": "提问过于宽泛，没有指向具体的表或数据内容",
            "low_confidence_raw_lookup": "无法确定提问的具体分析意图",
            "analytical_no_table_no_dims": "需要进行分析但未指明分析哪个表",
            "too_short_no_entities": "提问过短，缺少关键信息",
        }
        reason_desc = reason_labels.get(reason, "提问信息不够具体")

        return (
            f"用户提问：{query}\n\n"
            f"问题：{reason_desc}\n\n"
            f"{schema_summary}\n\n"
            "请生成一个友好的反问，帮助用户明确需求。"
        )

    def _fallback_question(
        self, query: str, detect_result: dict, ctx
    ) -> ClarificationQuestion:
        """LLM 不可用时的基于规则的降级方案。"""
        tables = ctx.table_names or []
        table_hint = f"可用的数据表包括：{', '.join(tables[:5])}" if tables else ""

        return ClarificationQuestion(
            question_id=str(uuid.uuid4()),
            question_text=(
                f"你的提问「{query[:80]}」信息不够具体，我暂时无法确定你想查询什么数据。"
                f"能否补充以下信息？\n"
                f"1. 你想查询哪个表或哪类数据？{table_hint}\n"
                f"2. 你想看什么指标？（如数量、金额、趋势等）\n"
                f"3. 有什么筛选条件或时间范围？"
            ),
            missing_entities=[],
            suggested_options=(
                [f"查看 {t} 表的数据概览" for t in tables[:3]]
                if tables
                else []
            ),
        )


CLARIFICATION_SYSTEM_PROMPT = """你是一个数据分析助手，当用户的提问太模糊时，你需要友好地反问以帮助用户明确需求。

输出格式必须是 JSON：
{
  "question_text": "友好的反问文本，说明为什么需要更多信息，具体需要什么",
  "missing_entities": ["缺失的概念1", "缺失的概念2"],
  "suggested_options": ["具体的建议提问1", "具体的建议提问2", "具体的建议提问3"]
}

规则：
- question_text 要友好、有帮助，不要生硬
- 必须明确指出缺少什么信息（表名？指标？时间范围？筛选条件？）
- suggested_options 提供 3-5 个具体、可执行的提问示例
- 建议提问要基于可用表的实际名称，写完整的 SQL 式提问
- 如果可用表中有中文注释，优先使用业务友好的表达
- 不要猜测用户的意图，而是引导用户补充信息
- 建议选项要多样化，覆盖不同可能的查询方向

只输出 JSON，不输出其他文本。"""