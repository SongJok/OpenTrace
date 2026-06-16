"""
SemanticAgent — 将业务概念解析为 SQL 片段。

结合知识层（matched_metrics、column_semantics）与 SemanticLayer，
做配置驱动的维度/指标/时间解析。

核心逻辑无 LLM；仅歧义概念消歧时使用 LLM。
"""
from __future__ import annotations

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class SemanticAgent(BaseAgent):
    """将用户查询中的业务概念解析为 SQL 片段。

    该 Agent 桥接"业务语言"与"数据库语言"：
    - "高价值用户" → tier IN ('TIAN_DI', 'TIAN_ZUN')
    - "GMV" → SUM(paid_amount) FILTER (WHERE status != 'refunded')
    - "最近7天" → created_at >= now() - interval '7 days'
    """

    def __init__(self) -> None:
        super().__init__("data_semantic")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        try:
            semantic_context = await self._resolve_semantics(ctx)
            ctx.semantic_context = semantic_context

            dimension_count = len(semantic_context.get("dimension_mappings", {}))
            metric_count = len(semantic_context.get("metric_defs", {}))
            time_count = len(semantic_context.get("time_macros", []))

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=f"resolved {dimension_count} dims, {metric_count} metrics, {time_count} time macros",
                confidence=self._semantic_confidence(
                    dimension_count, metric_count, time_count
                ),
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="semantic_agent",
                    source_type="data_cognition",
                    payload=semantic_context,
                    credibility=0.90,
                    relevance=0.95,
                )],
            )
        except Exception as exc:
            ctx.semantic_context = {
                "dimension_mappings": {},
                "metric_defs": {},
                "time_macros": [],
                "resolved_sql_fragments": "",
            }
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="semantic resolution failed, continuing with empty context",
                confidence=0.2,
                metadata={"cognitive_context": ctx.to_dict()},
                error=str(exc),
            )

    async def _resolve_semantics(self, ctx: CognitiveContext) -> dict:
        """从知识层与配置构建语义上下文。"""

        # 1. 维度映射：来自 schema_metadata 的 value_map
        dimension_mappings: dict = {}
        if ctx.column_semantics:
            for col in ctx.column_semantics:
                if col.get("is_dimension_column") and col.get("value_map"):
                    dim_name = col.get("business_name") or col["column_name"]
                    dimension_mappings[dim_name] = {
                        "column": f"{col['table_name']}.{col['column_name']}",
                        "table": col["table_name"],
                        "value_map": col["value_map"],
                        "description": col.get("business_description", ""),
                    }

        # 2. 指标定义：来自知识层的 matched_metrics
        metric_defs: dict = {}
        if ctx.matched_metrics:
            for m in ctx.matched_metrics:
                name = m["name"]
                metric_defs[name] = m["formula"]
        # 同时从 semantic_config 补充尚未覆盖的指标
        config_metrics = ctx.semantic_config.get("metrics", {})
        for name, formula in config_metrics.items():
            if name not in metric_defs:
                metric_defs[name] = formula

        # 3. 时间宏：来自 semantic_config
        time_macros = list(ctx.semantic_config.get("time_macros", []))

        # 4. 已解析的 SQL 片段
        resolved_fragments = self._build_resolved_fragments(
            dimension_mappings, metric_defs, ctx
        )

        return {
            "dimension_mappings": dimension_mappings,
            "metric_defs": metric_defs,
            "time_macros": time_macros,
            "resolved_sql_fragments": resolved_fragments,
        }

    def _build_resolved_fragments(
        self,
        dims: dict,
        metrics: dict,
        ctx: CognitiveContext,
    ) -> str:
        """构建供下游 Agent 使用的人类可读 SQL 片段摘要。"""
        parts: list[str] = []

        # 维度 WHERE 子句（来自 value_map）
        query_lower = ctx.query.lower()
        for name, dim in dims.items():
            value_map = dim.get("value_map", {})
            if value_map:
                for key, label in value_map.items():
                    if label.lower() in query_lower or key.lower() in query_lower:
                        col = dim["column"]
                        parts.append(f"-- {name}={label} → {col} = '{key}'")

        # 指标 SELECT 表达式
        for name, formula in metrics.items():
            if name.lower() in query_lower:
                parts.append(f"-- {name} → {formula}")

        return "\n".join(parts)

    def _semantic_confidence(
        self, dims: int, metrics: int, times: int
    ) -> float:
        if dims + metrics + times == 0:
            return 0.3
        # 解析的概念越多，置信度越高
        return min(0.3 + 0.1 * (dims + metrics + times), 0.95)
