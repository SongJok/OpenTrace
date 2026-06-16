"""
MetricAgent — 将业务指标提及映射到列与聚合函数。

以知识层 metric_definitions 为主数据源；
回退 SchemaLinker.link_metrics() 模式字典与 LLM。
"""
from __future__ import annotations

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class MetricAgent(BaseAgent):
    """识别并定位用户查询中的指标引用。

    优先级：
    1. metric_definitions（知识层 — 权威来源）
    2. 内置模式字典（SchemaLinker.link_metrics）
    3. LLM 回退
    """

    def __init__(self) -> None:
        super().__init__("data_metric")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        try:
            metrics = await self._resolve_metrics(ctx)
            ctx.metrics = metrics

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=f"resolved {len(metrics)} metrics",
                confidence=self._metric_confidence(metrics),
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="metric_resolver",
                    source_type="data_cognition",
                    payload={"metrics": metrics},
                    credibility=0.90,
                    relevance=1.0,
                )],
            )
        except Exception as exc:
            ctx.metrics = []
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="metric resolution failed",
                confidence=0.2,
                metadata={"cognitive_context": ctx.to_dict()},
                error=str(exc),
            )

    async def _resolve_metrics(self, ctx: CognitiveContext) -> list[dict]:
        metrics: list[dict] = []
        query_lower = ctx.query.lower()

        # 优先级 1：知识层 matched_metrics
        if ctx.matched_metrics:
            for m in ctx.matched_metrics:
                name_lower = (m["name"] or "").lower()
                alias_match = any(
                    (a or "").lower() in query_lower
                    for a in (m.get("aliases") or [])
                )
                name_match = name_lower and name_lower in query_lower
                if name_match or alias_match:
                    metrics.append({
                        "mention": m["name"],
                        "mapped_column": m["underlying_columns"][0] if m["underlying_columns"] else "",
                        "agg": m.get("agg_function") or "SUM",
                        "formula": m["formula"],
                        "business_definition": m.get("business_definition", ""),
                        "source": "metric_definitions",
                        "confidence": 0.95,
                    })

        # 优先级 2：内置模式字典
        if not metrics:
            metrics = await self._fallback_pattern_dict(ctx)

        # 优先级 3：LLM 回退
        if not metrics:
            metrics = await self._fallback_llm(ctx)

        return metrics

    async def _fallback_pattern_dict(self, ctx: CognitiveContext) -> list[dict]:
        """使用 SchemaLinker.link_metrics() 模式字典。"""
        from kernel.data_cognition.schema_linker import SchemaLinker

        linker = SchemaLinker(
            table_names=ctx.table_names,
            table_columns=ctx.table_columns,
        )
        mappings = await linker.link_metrics(ctx.query)
        return [
            {
                "mention": m.mention,
                "mapped_column": m.mapped_column,
                "agg": m.agg,
                "source": "pattern_dict",
                "confidence": m.confidence,
            }
            for m in mappings
        ]

    async def _fallback_llm(self, ctx: CognitiveContext) -> list[dict]:
        """基于 LLM 的回退方案，用于新指标。"""
        from kernel.data_cognition.schema_linker import SchemaLinker

        linker = SchemaLinker(
            table_names=ctx.table_names,
            table_columns=ctx.table_columns,
        )
        # 强制走 LLM 路径（提供空列）
        try:
            mappings = await linker.link_metrics(ctx.query)
            return [
                {
                    "mention": m.mention,
                    "mapped_column": m.mapped_column,
                    "agg": m.agg,
                    "source": "llm_fallback",
                    "confidence": m.confidence,
                }
                for m in mappings
            ]
        except Exception:
            return []

    def _metric_confidence(self, metrics: list[dict]) -> float:
        if not metrics:
            return 0.0
        avg = sum(m.get("confidence", 0.5) for m in metrics) / len(metrics)
        return min(avg, 0.98)
