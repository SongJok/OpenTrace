from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelRouteDecision:
    complexity: str
    reasoning_strategy: str
    temperature: float


class ModelRouter:
    """Task-aware model/strategy router for P1 baseline."""

    def route(self, query: str, metadata: dict[str, object] | None = None) -> ModelRouteDecision:
        q = query.lower()
        metadata = metadata or {}
        db_tokens = ["数据库", "表", "schema", "字段", "列", "sql", "查询", "数据源", "test_db", "information_schema", "show tables"]
        db_context = bool(metadata.get("data_source_id") or metadata.get("data_source_schema")) or any(k in q for k in db_tokens)
        complex_hit = any(k in q for k in ["设计", "架构", "tradeoff", "对比", "深入", "优化方案"])
        code_hit = any(k in q for k in ["代码", "python", "debug", "implement", "重构"])
        analysis_hit = any(k in q for k in ["分析", "统计", "预测", "data"])

        if db_context:
            return ModelRouteDecision(complexity="medium", reasoning_strategy="COT", temperature=0.15)
        if complex_hit:
            return ModelRouteDecision(complexity="complex", reasoning_strategy="TOT", temperature=0.25)
        if code_hit or analysis_hit:
            return ModelRouteDecision(complexity="medium", reasoning_strategy="COT", temperature=0.2)
        return ModelRouteDecision(complexity="simple", reasoning_strategy="DIRECT", temperature=0.1)
