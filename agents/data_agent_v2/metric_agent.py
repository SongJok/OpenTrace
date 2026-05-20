"""
MetricAgent — maps business metric mentions to column + aggregation functions.

Uses metric_definitions from Knowledge Layer as the primary source of truth.
Falls back to SchemaLinker.link_metrics() pattern dictionary + LLM.
"""
from __future__ import annotations

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class MetricAgent(BaseAgent):
    """Identify and ground metric references in the user query.

    Priority order:
    1. metric_definitions (Knowledge Layer — authoritative)
    2. Built-in pattern dictionary (SchemaLinker.link_metrics)
    3. LLM fallback
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

        # Priority 1: Knowledge Layer matched_metrics
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

        # Priority 2: Built-in pattern dictionary
        if not metrics:
            metrics = await self._fallback_pattern_dict(ctx)

        # Priority 3: LLM fallback
        if not metrics:
            metrics = await self._fallback_llm(ctx)

        return metrics

    async def _fallback_pattern_dict(self, ctx: CognitiveContext) -> list[dict]:
        """Use SchemaLinker.link_metrics() pattern dictionary."""
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
        """LLM-based fallback for novel metrics."""
        from kernel.data_cognition.schema_linker import SchemaLinker

        linker = SchemaLinker(
            table_names=ctx.table_names,
            table_columns=ctx.table_columns,
        )
        # Force LLM path by providing empty columns
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
