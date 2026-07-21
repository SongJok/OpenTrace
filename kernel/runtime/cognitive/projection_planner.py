"""Execution projection only — separates DAG projection from strategic/ cognitive planning."""

from __future__ import annotations

from typing import Any


class ProjectionPlanner:
    def project(
        self,
        strategy: Any,
        *,
        query: str,
        intent_category: str = "general",
        risk_level: str = "low",
        completion_criteria: str = "",
        ctx: Any | None = None,
    ) -> tuple[Any, Any]:
        from kernel.runtime.cognitive.execution_projection import build_execution_projection

        projection = build_execution_projection(
            strategy,
            query=query,
            intent_category=intent_category,
            risk_level=risk_level,
            completion_criteria=completion_criteria,
        )
        return projection.to_execution_plan(), projection.to_execution_graph(ctx)


def get_projection_planner() -> ProjectionPlanner:
    return ProjectionPlanner()