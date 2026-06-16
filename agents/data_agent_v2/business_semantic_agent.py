"""
BusinessSemanticAgent — KPI / period-over-period business semantics for data queries.

Runs after metric/time agents; enriches CognitiveContext with business_kpis and annotations.
"""

from __future__ import annotations

import re
from typing import Any

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import pack_cognitive_result, unpack_cognitive_context

# keyword → (kpi_id, label, default_grain)
_KPI_LEXICON: tuple[tuple[str, str, str, str], ...] = (
    (r"销售|营收|收入|gmv|revenue", "revenue", "收入", "mom_yoy"),
    (r"成本|费用|支出|cost", "cost", "成本", "mom"),
    (r"利润|毛利|净利|margin", "margin", "利润", "mom_yoy"),
    (r"客单价|arpu|客单", "arpu", "客单价", "mom"),
    (r"转化|转化率|conversion", "conversion_rate", "转化率", "wow"),
    (r"复购|留存|retention", "retention", "复购/留存", "mom"),
    (r"渠道|channel", "channel_contribution", "渠道贡献", "period"),
    (r"同比|环比|yoy|mom|wow", "period_compare", "同环比", "auto"),
)


def infer_business_kpis(query: str, intent: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Deterministic KPI inference from query text (no LLM)."""
    q = (query or "").lower()
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern, kpi_id, label, grain in _KPI_LEXICON:
        if re.search(pattern, q, re.I):
            if kpi_id in seen:
                continue
            seen.add(kpi_id)
            found.append(
                {
                    "kpi_id": kpi_id,
                    "label": label,
                    "comparison": grain,
                    "confidence": 0.85,
                }
            )
    if not found and intent:
        it = str(intent.get("intent_type") or intent.get("task_type") or "")
        if it in ("analytics", "data_query", "metric"):
            found.append(
                {
                    "kpi_id": "revenue",
                    "label": "收入",
                    "comparison": "mom_yoy",
                    "confidence": 0.55,
                    "inferred_default": True,
                }
            )
    return found


def build_business_semantic_bundle(
    query: str,
    ctx_metrics: dict[str, Any] | None,
    intent: dict[str, Any] | None,
) -> dict[str, Any]:
    kpis = infer_business_kpis(query, intent)
    anomalies: list[str] = []
    if kpis and len(kpis) >= 3:
        anomalies.append("multi_kpi_query_consider_clarify_grain")
    metric_names = set()
    if ctx_metrics:
        for m in ctx_metrics.get("metrics") or ctx_metrics.get("matched_metrics") or []:
            if isinstance(m, dict):
                metric_names.add(str(m.get("name") or m.get("metric_id") or ""))
            else:
                metric_names.add(str(m))
    if metric_names and kpis:
        for k in kpis:
            k["aligned_metrics"] = [n for n in metric_names if n][:5]
    return {
        "business_kpis": kpis,
        "kpi_count": len(kpis),
        "anomaly_hints": anomalies,
        "clarification_focus": "metric_definition" if kpis else "schema",
    }


class BusinessSemanticAgent(BaseAgent):
    """Maps colloquial business questions to KPI sets and comparison semantics."""

    def __init__(self) -> None:
        super().__init__("data_business_semantic")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)
        metric_ctx = None
        if ctx.metrics:
            metric_ctx = {"metrics": ctx.metrics, "matched_metrics": ctx.matched_metrics}
        bundle = build_business_semantic_bundle(ctx.query, metric_ctx, ctx.intent)
        ctx.business_semantic = bundle
        conf = 0.75 if bundle["kpi_count"] else 0.4
        return pack_cognitive_result(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=f"business_kpis={bundle['kpi_count']}",
            confidence=conf,
            ctx=ctx,
            evidence=[
                self._make_evidence(
                    source="business_semantic",
                    source_type="data_cognition",
                    payload=bundle,
                    credibility=conf,
                    relevance=0.9,
                )
            ],
        )