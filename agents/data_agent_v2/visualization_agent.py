"""
VisualizationAgent — 为数据结果推荐图表类型与配置。

分析数据结构（列、类型、行数、基数）与意图，推荐最优可视化：
- 列类型（数值、分类、时间）
- 行数与基数
- 意图（趋势→折线、构成→饼图、排名→柱状等）
- 分析技能提示（matched_skills）

返回适配 DataTableChart 前端的图表配置；无 LLM，完全确定性。
"""
from __future__ import annotations

from typing import Any

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class VisualizationAgent(BaseAgent):
    """为数据结果推荐最优图表类型与配置。

    确定性逻辑。分析数据结构与意图，生成前端可用的图表配置。
    """

    # 按意图优先的图表类型映射
    INTENT_CHART_MAP: dict[str, list[str]] = {
        "trend": ["line", "area", "bar"],
        "comparison": ["grouped_bar", "bar", "radar"],
        "ranking": ["horizontal_bar", "bar", "table"],
        "composition": ["pie", "donut", "stacked_bar", "treemap"],
        "distribution": ["histogram", "box_plot", "violin"],
        "funnel": ["funnel", "bar"],
        "cohort": ["heatmap", "table"],
        "anomaly_detection": ["scatter", "line", "heatmap"],
        "aggregation": ["bar", "metric_card", "table"],
        "raw_lookup": ["table", "metric_card"],
        "metadata": ["table"],
    }

    def __init__(self) -> None:
        super().__init__("data_visualization")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        rows = ctx.execution_rows or []
        if not rows:
            return self._skip(task, ctx, "no data to visualize")

        try:
            # 1. 分析数据结构
            structure = self._analyze_structure(rows, ctx)

            # 2. 确定图表类型
            chart_config = self._recommend(ctx, structure, rows)

            # 3. 构建完整配置
            config = self._build_config(chart_config, structure, rows)

            ctx.visualization_config = config

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=f"chart: {config['chart_type']} ({config.get('title', '')})",
                confidence=0.90,
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="visualization_agent",
                    source_type="analysis",
                    payload={
                        "chart_type": config["chart_type"],
                        "x_axis": config.get("x_axis"),
                        "y_axis": config.get("y_axis"),
                        "alternatives": config.get("alternatives", []),
                    },
                    credibility=0.90,
                    relevance=0.90,
                )],
                agent_trace={
                    "chart_type": config["chart_type"],
                    "structure": structure,
                },
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="visualization recommendation skipped",
                confidence=0.5,
                metadata={"cognitive_context": ctx.to_dict()},
                error=str(exc),
            )

    # ── 数据结构分析 ─────────────────────────────────────────

    def _analyze_structure(
        self, rows: list[dict], ctx: CognitiveContext
    ) -> dict[str, Any]:
        """分析结果行的结构以评估图表适配性。"""
        if not rows:
            return {}

        first_row = rows[0]
        columns: dict[str, dict] = {}

        for col, val in first_row.items():
            col_info: dict[str, Any] = {
                "name": col,
                "sample": val,
                "type": self._infer_col_type(col, val, rows),
                "null_count": sum(1 for r in rows if r.get(col) is None),
                "unique_count": len({str(r.get(col)) for r in rows[:500]}),
            }

            if col_info["type"] == "numeric":
                values = [
                    float(r[col]) for r in rows
                    if r.get(col) is not None
                    and isinstance(r[col], (int, float))
                    and not isinstance(r[col], bool)
                ]
                if values:
                    col_info["min"] = min(values)
                    col_info["max"] = max(values)

            columns[col] = col_info

        return {
            "columns": columns,
            "row_count": len(rows),
            "col_count": len(columns),
            "numeric_cols": [
                c for c, info in columns.items() if info["type"] == "numeric"
            ],
            "temporal_cols": [
                c for c, info in columns.items() if info["type"] == "temporal"
            ],
            "categorical_cols": [
                c for c, info in columns.items() if info["type"] == "categorical"
            ],
            "has_time_series": any(
                info["type"] == "temporal" for info in columns.values()
            ),
        }

    def _infer_col_type(
        self, col: str, sample: Any, rows: list[dict]
    ) -> str:
        """推断列数据类型。"""
        # 时间类型检测
        temporal_hints = ("date", "time", "日期", "时间", "year", "month", "day",
                         "created", "updated", "timestamp", "ds", "dt")
        if any(h in col.lower() for h in temporal_hints):
            return "temporal"

        if isinstance(sample, (int, float)) and not isinstance(sample, bool):
            return "numeric"

        # 分类类型检测：低基数字符串
        if isinstance(sample, str):
            unique = len({str(r.get(col)) for r in rows[:100]})
            if unique <= 15:
                return "categorical"
            return "text"

        if isinstance(sample, bool):
            return "categorical"

        return "unknown"

    # ── 图表推荐 ────────────────────────────────────────────

    def _recommend(
        self,
        ctx: CognitiveContext,
        structure: dict,
        rows: list[dict],
    ) -> dict[str, Any]:
        """根据数据与意图确定最优图表类型。"""
        intent_type = (
            ctx.intent.get("intent_type", "") if ctx.intent else ""
        )

        # 1. 检查技能提示
        skill_hint = ""
        if ctx.matched_skills:
            skill_hint = ctx.matched_skills[0].get("visualization_hint", "")

        # 2. 根据数据确定可用图表类型
        numeric = structure.get("numeric_cols", [])
        temporal = structure.get("temporal_cols", [])
        categorical = structure.get("categorical_cols", [])
        row_count = structure.get("row_count", 0)

        candidates: list[str] = []

        # 时间序列 → 折线/面积图
        if temporal and numeric:
            candidates.extend(["line", "area"])
            if len(numeric) >= 2:
                candidates.append("multi_line")

        # 数值 + 分类 → 柱状/分组柱状图
        if numeric and categorical:
            candidates.extend(["bar", "grouped_bar", "horizontal_bar"])
            if len(categorical) == 1 and len(numeric) >= 2:
                candidates.append("stacked_bar")

        # 单数值 + 分类（少量值）→ 饼图/环形图
        if len(numeric) == 1 and categorical and row_count <= 10:
            candidates.extend(["pie", "donut"])

        # 多数值，无明确分类 → 散点图
        if len(numeric) >= 2 and not categorical:
            candidates.append("scatter")

        # 大行数 + 时间 → 面积/迷你折线图
        if temporal and numeric and row_count > 20:
            candidates.append("area")

        # Low row count, single metric → metric_card
        if row_count == 1 and len(numeric) >= 1:
            candidates.append("metric_card")

        # Heatmap for matrix-like data
        if len(categorical) >= 2 and numeric:
            candidates.append("heatmap")

        # Table always available as fallback
        if "table" not in candidates:
            candidates.append("table")

        # 3. Prioritize by intent
        intent_prefs = self.INTENT_CHART_MAP.get(intent_type, ["bar", "table"])
        scored: list[tuple[str, float]] = []

        for chart in candidates:
            score = 0.5  # Base score

            # Intent match bonus
            if chart in intent_prefs:
                score += 0.3 * (1 - intent_prefs.index(chart) / len(intent_prefs))

            # Skill hint bonus
            if chart == skill_hint:
                score += 0.2

            # Data suitability bonus
            if chart == "line" and temporal:
                score += 0.15
            if chart == "pie" and row_count <= 10 and len(numeric) == 1:
                score += 0.15
            if chart == "heatmap" and len(categorical) >= 2:
                score += 0.1

            scored.append((chart, round(score, 3)))

        scored.sort(key=lambda x: x[1], reverse=True)

        primary = scored[0]
        alternatives = [s[0] for s in scored[1:4]]

        return {
            "primary": primary[0],
            "score": primary[1],
            "alternatives": alternatives[:3],
            "all_scored": scored,
        }

    def _build_config(
        self,
        chart_recommendation: dict,
        structure: dict,
        rows: list[dict],
    ) -> dict[str, Any]:
        """Build full chart configuration for frontend."""
        chart_type = chart_recommendation["primary"]
        numeric = structure.get("numeric_cols", [])
        temporal = structure.get("temporal_cols", [])
        categorical = structure.get("categorical_cols", [])

        config: dict[str, Any] = {
            "chart_type": chart_type,
            "title": "",
            "x_axis": "",
            "y_axis": [],
            "series": [],
            "alternatives": chart_recommendation.get("alternatives", []),
            "data_source": "query_result",
            "options": {},
        }

        # Assign axes based on chart type
        if chart_type in ("line", "area"):
            config["x_axis"] = temporal[0] if temporal else categorical[0] if categorical else ""
            config["y_axis"] = numeric[:3]
            config["options"]["smooth"] = len(rows) <= 30

        elif chart_type in ("bar", "grouped_bar", "horizontal_bar"):
            config["x_axis"] = categorical[0] if categorical else ""
            config["y_axis"] = numeric[:5]
            if chart_type == "horizontal_bar":
                config["options"]["swap_axes"] = True

        elif chart_type in ("stacked_bar",):
            config["x_axis"] = categorical[0] if categorical else ""
            config["y_axis"] = numeric[:5]
            config["options"]["stacked"] = True

        elif chart_type in ("pie", "donut"):
            config["x_axis"] = categorical[0] if categorical else ""
            config["y_axis"] = [numeric[0]] if numeric else []
            if chart_type == "donut":
                config["options"]["inner_radius"] = 0.6

        elif chart_type == "scatter":
            config["x_axis"] = numeric[0] if len(numeric) >= 1 else ""
            config["y_axis"] = [numeric[1]] if len(numeric) >= 2 else numeric[:1]
            config["options"]["point_size"] = min(10, max(3, 100 // max(1, len(rows))))

        elif chart_type == "heatmap":
            config["x_axis"] = categorical[0] if len(categorical) >= 1 else ""
            config["y_axis"] = categorical[1] if len(categorical) >= 2 else ""
            config["series"] = [numeric[0]] if numeric else []
            config["options"]["color_scheme"] = "blues"

        elif chart_type == "metric_card":
            # Single metric display
            if numeric and rows:
                val = rows[0].get(numeric[0])
                config["options"]["value"] = val
                config["options"]["label"] = numeric[0]
                config["options"]["format"] = "number"

        elif chart_type == "table":
            config["columns"] = list(rows[0].keys()) if rows else []
            config["options"]["page_size"] = min(50, len(rows))
            config["options"]["sortable"] = True

        # Generic: assign best-guess axes
        if not config["x_axis"]:
            if temporal:
                config["x_axis"] = temporal[0]
            elif categorical:
                config["x_axis"] = categorical[0]
        if not config["y_axis"]:
            config["y_axis"] = numeric[:3]

        return config

    def _skip(
        self, task: TaskMessage, ctx: CognitiveContext, reason: str
    ) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=f"visualization skipped: {reason}",
            confidence=0.5,
            metadata={"cognitive_context": ctx.to_dict()},
            agent_trace={"skip_reason": reason},
        )
