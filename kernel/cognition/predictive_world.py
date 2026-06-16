"""Predictive world slice — lightweight trend / impact hints for decision narrative."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PredictedState:
    metric: str = ""
    direction: str = "stable"  # up | down | stable | unknown
    confidence: float = 0.0
    horizon: str = "short"  # short | medium
    narrative: str = ""
    factors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "horizon": self.horizon,
            "narrative": self.narrative[:500],
            "factors": list(self.factors),
        }


def predict_from_time_series_stub(
  values: list[float],
  *,
  metric_name: str = "value",
) -> PredictedState:
    """Deterministic stub: last-two-point slope."""
    if len(values) < 2:
        return PredictedState(
            metric=metric_name,
            direction="unknown",
            confidence=0.2,
            narrative="数据点不足，无法外推。",
        )
    a, b = float(values[-2]), float(values[-1])
    if b > a * 1.02:
        direction = "up"
        narrative = f"{metric_name} 近期呈上升趋势，短期可能继续走高（启发式）。"
    elif b < a * 0.98:
        direction = "down"
        narrative = f"{metric_name} 近期呈下降趋势，需关注库存或收入影响（启发式）。"
    else:
        direction = "stable"
        narrative = f"{metric_name} 近期波动不大，维持观察。"
    conf = min(0.75, 0.35 + 0.1 * len(values))
    return PredictedState(
        metric=metric_name,
        direction=direction,
        confidence=conf,
        narrative=narrative,
        factors=["last_two_points_slope"],
    )


def enrich_world_projection_with_predictions(
    world_projection: dict[str, Any],
    *,
    query: str = "",
    data_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach predictive slice to goal_world_projection metadata."""
    out = dict(world_projection or {})
    predictions: list[dict[str, Any]] = []
    if data_rows:
        for row in data_rows[:3]:
            nums = [float(v) for k, v in row.items() if isinstance(v, (int, float))]
            if len(nums) >= 2:
                predictions.append(
                    predict_from_time_series_stub(nums, metric_name=str(row.get("metric", "series"))).to_dict()
                )
    if not predictions and query:
        q = query.lower()
        if any(x in q for x in ("库存", "inventory", "销售", "revenue")):
            predictions.append(
                PredictedState(
                    metric="business_kpi",
                    direction="unknown",
                    confidence=0.4,
                    narrative="建议在数据查询结果返回后绑定时序外推。",
                    factors=["query_hint_only"],
                ).to_dict()
            )
    out["predictive"] = {"predictions": predictions, "enabled": True}
    return out