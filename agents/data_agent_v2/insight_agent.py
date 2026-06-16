"""
InsightAgent — 从数据结果生成自然语言洞察。

输入结构化数据（行 + 统计发现 + 意图），输出：
- 关键观察
- 模式（趋势、离群、分组）
- 异常（统计显著偏离）
- 建议（可执行的下一步）

LLM（PLANNING）+ 确定性回退。
"""
from __future__ import annotations

from typing import Any

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class InsightAgent(BaseAgent):
    """从结构化数据结果生成自然语言洞察。

    使用 LLM 解读统计发现、数据模式和业务上下文，
    输出人类可读的观察和建议。
    """

    def __init__(self) -> None:
        super().__init__("data_insight")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        rows = ctx.execution_rows or []
        if not rows:
            return self._skip(task, ctx, "no data to generate insights from")

        try:
            insights = await self._generate_insights(ctx, rows)
            ctx.insights = insights

            summary = insights.get("summary", "")
            observations = insights.get("observations", [])
            recs = insights.get("recommendations", [])

            content_parts = [summary]
            if observations:
                content_parts.append(
                    "关键发现:\n" + "\n".join(f"• {o}" for o in observations[:5])
                )
            if recs:
                content_parts.append(
                    "建议:\n" + "\n".join(f"→ {r}" for r in recs[:3])
                )

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="\n\n".join(content_parts),
                confidence=insights.get("confidence", 0.75),
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="insight_agent",
                    source_type="analysis",
                    payload={
                        "observation_count": len(observations),
                        "recommendation_count": len(recs),
                        "insight_type": insights.get("insight_type", ""),
                    },
                    credibility=0.80,
                    relevance=0.90,
                )],
                agent_trace={
                    "insight_type": insights.get("insight_type"),
                    "observations": observations,
                    "recommendations": recs,
                },
            )
        except Exception as exc:
            # 回退到启发式洞察
            insights = self._heuristic_insights(ctx, rows)
            ctx.insights = insights
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=insights.get("summary", "insights generated"),
                confidence=0.6,
                metadata={"cognitive_context": ctx.to_dict()},
                agent_trace={"warning": f"LLM insights failed, using heuristics: {exc}"},
            )

    async def _generate_insights(
        self, ctx: CognitiveContext, rows: list[dict]
    ) -> dict[str, Any]:
        """基于 LLM 的洞察生成。"""
        from model.model_gateway.gateway import LLMRole, get_model_gateway
        from model.llm_adapter.base import LLMMessage

        prompt = self._build_insight_prompt(ctx, rows)

        try:
            gw = get_model_gateway()
            response = await gw.chat(
                messages=[
                    LLMMessage(role="system", content=INSIGHT_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=prompt),
                ],
                role=LLMRole.PLANNING,
                temperature=0.2,
                max_tokens=600,
            )

            import json
            return json.loads(response.content.strip())
        except Exception:
            raise

    def _build_insight_prompt(self, ctx: CognitiveContext, rows: list[dict]) -> str:
        """从上下文构建洞察生成提示。"""
        parts = [f"Query: {ctx.query}"]

        if ctx.intent:
            parts.append(f"Intent: {ctx.intent.get('intent_type', '')}")
            parts.append(f"Target: {ctx.intent.get('target_entity', '')} / {ctx.intent.get('metric', '')}")

        # 数据摘要
        parts.append(f"Rows returned: {len(rows)}")
        if rows:
            parts.append(f"Columns: {', '.join(list(rows[0].keys())[:15])}")

        # 样本行
        sample = rows[:5]
        parts.append(f"Sample data ({len(sample)} rows):")
        for i, r in enumerate(sample):
            parts.append(f"  Row {i+1}: {str(r)[:300]}")

        # 已执行的 SQL（帮助理解查询逻辑）
        if ctx.compiled_sql:
            parts.append(f"\nExecuted SQL:\n```sql\n{ctx.compiled_sql}\n```")

        # Schema 上下文（表/列注释，用于业务语义）
        if ctx.schema_hint:
            parts.append(f"\nSchema context:\n{ctx.schema_hint[:2000]}")

        # 统计发现
        stats = ctx.statistical_report or {}
        if stats.get("descriptive_stats"):
            parts.append("\nStatistical findings:")
            for col, s in stats["descriptive_stats"].items():
                parts.append(
                    f"  {col}: mean={s.get('mean')}, median={s.get('median')}, "
                    f"std={s.get('std')}, range=[{s.get('min')}, {s.get('max')}]"
                )

        if stats.get("trends"):
            parts.append("\nTrends detected:")
            for col, t in stats["trends"].items():
                parts.append(
                    f"  {col}: {t.get('direction')} ({t.get('strength_label')}), "
                    f"change: {t.get('change_pct')}%"
                )

        if stats.get("outliers"):
            parts.append("\nOutliers detected:")
            for col, vals in stats["outliers"].items():
                parts.append(f"  {col}: {len(vals)} outliers")

        # 指标上下文
        if ctx.metrics:
            metric_strs = [
                f"{m.get('mention', '')} ({m.get('agg_function', '')})"
                for m in ctx.metrics[:5]
            ]
            parts.append(f"\nMetrics: {', '.join(metric_strs)}")

        # 时间上下文
        if ctx.time_window and ctx.time_window.get("type") not in (None, "none"):
            parts.append(f"Time window: {ctx.time_window.get('description', '')}")

        # 实体上下文
        if ctx.entities:
            entity_strs = [
                f"{e.get('mention', '')} → {e.get('mapped_table', '')}"
                for e in ctx.entities[:5]
            ]
            parts.append(f"\nEntities: {', '.join(entity_strs)}")

        return "\n".join(parts)

    def _heuristic_insights(
        self, ctx: CognitiveContext, rows: list[dict]
    ) -> dict[str, Any]:
        """不依赖 LLM 的确定性洞察生成。"""

        observations: list[str] = []
        recommendations: list[str] = []

        # 行数观察
        if len(rows) == 0:
            return {
                "summary": "查询未返回数据，建议调整过滤条件或扩大时间范围。",
                "observations": ["无匹配数据"],
                "recommendations": ["尝试放宽过滤条件", "检查时间范围是否过于严格"],
                "confidence": 0.8,
                "insight_type": "empty_result",
            }

        observations.append(f"查询返回了 {len(rows)} 行数据。")

        # 统计洞察
        stats = ctx.statistical_report or {}
        if stats.get("trends"):
            for col, t in stats["trends"].items():
                if t.get("direction") == "increasing" and t.get("strength", 0) > 0.5:
                    observations.append(f"{col} 呈明显上升趋势 (变化幅度 {t.get('change_pct', '?')}%)")
                elif t.get("direction") == "decreasing" and t.get("strength", 0) > 0.5:
                    observations.append(f"{col} 呈明显下降趋势，需要关注")
                    recommendations.append(f"建议深入分析 {col} 下降的原因")

        if stats.get("outliers"):
            total = sum(len(v) for v in stats["outliers"].values())
            if total > 0:
                observations.append(f"检测到 {total} 个异常值")
                recommendations.append("建议核实异常值的业务合理性")

        if stats.get("group_comparisons"):
            for dim, cols in stats["group_comparisons"].items():
                for col, c in cols.items():
                    observations.append(
                        f"{dim} 维度下 {col} 最高为 {c['max_group']}，"
                        f"最低为 {c['min_group']}（差距 {c.get('ratio', '?')} 倍）"
                    )

        # 基于意图的洞察
        intent_type = ctx.intent.get("intent_type", "") if ctx.intent else ""
        if intent_type == "ranking" and len(rows) > 1:
            first = rows[0]
            last = rows[-1]
            observations.append(
                f"排名第一和最后之间存在显著差异"
            )

        # 构建引用用户原始问题的摘要
        query_brief = (ctx.query or "")[:80]
        summary = f"「{query_brief}」查询完成。" + (
            f" 共发现 {len(observations)} 个关键发现。" if observations else ""
        )

        # 若用户询问趋势/原因分析但缺少相应能力，予以提示
        query_lower = (ctx.query or "").lower()
        if any(kw in query_lower for kw in ["趋势", "走势", "变化", "原因", "为什么"]):
            if not ctx.statistical_report:
                summary += " 注意：高级分析未启用，趋势和原因分析不可用。"

        return {
            "summary": summary,
            "observations": observations,
            "recommendations": recommendations,
            "confidence": 0.65,
            "insight_type": "heuristic",
        }

    def _skip(
        self, task: TaskMessage, ctx: CognitiveContext, reason: str
    ) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=f"insight generation skipped: {reason}",
            confidence=0.5,
            metadata={"cognitive_context": ctx.to_dict()},
            agent_trace={"skip_reason": reason},
        )


INSIGHT_SYSTEM_PROMPT = """You are a data analyst. Generate concise, actionable insights from structured query results.

Output JSON format:
{
  "summary": "1-2 sentence overview of key findings",
  "observations": ["observation 1", "observation 2", ...],
  "patterns": ["pattern description", ...],
  "anomalies": ["anomaly description", ...],
  "recommendations": ["actionable suggestion", ...],
  "insight_type": "trend|comparison|ranking|distribution|general",
  "confidence": 0.0-1.0
}

Rules:
- Be specific: use actual values from the data, not vague statements
- Be concise: each observation/recommendation under 80 characters
- Be actionable: recommendations should suggest what to do next
- Flag negatives: if the data shows problems, call them out
- Limit to 5 observations and 3 recommendations max

Analysis requirements:
- Your summary MUST address every analysis request in the user's query (e.g. if they asked for trends AND causes, cover both)
- If trend data is available, explain the direction (上升/下降/稳定), magnitude, and possible implications
- When suggesting causes, preface with "基于可用数据推断" and note which conclusions are data-driven vs speculative
- If the schema lacks time columns needed for trend analysis, explicitly state: "趋势分析需要时间字段（如 created_at/stat_date），当前表缺少明确的时间列，以下仅基于现有维度分析"
- If you cannot determine causes from available fields, state which fields would be needed for a proper diagnosis
- Use column comments and schema context to interpret field meanings in business terms
- Only output JSON"""
