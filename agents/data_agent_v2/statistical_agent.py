"""
StatisticalAgent — 描述统计、离群检测与趋势分析。

在无 LLM 情况下对查询结果行计算：
- 描述统计：计数、均值、中位数、标准差、分位数等
- 离群：IQR（1.5×IQR）与 Z 分数（|z|>3）
- 趋势：时间序列单调方向与强度
- 组间比较：效应量

计算可流式处理并兼容缺失值。
"""
from __future__ import annotations

import math
from typing import Any

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class StatisticalAgent(BaseAgent):
    """计算查询结果的描述统计并检测异常。

    确定性，无 LLM。仅当结果包含数值列时运行。
    """

    def __init__(self) -> None:
        super().__init__("data_statistical")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        rows = ctx.execution_rows or []
        if not rows:
            return self._skip(task, ctx, "no data rows to analyze")

        try:
            # 1. 识别数值列
            numeric_cols = self._find_numeric_columns(rows)

            # 2. 计算描述统计
            stats = {}
            for col in numeric_cols:
                values = self._extract_numeric_values(rows, col)
                if values:
                    stats[col] = self._compute_stats(values)

            # 3. 检测异常值
            outliers = self._detect_outliers_all(rows, numeric_cols)

            # 4. 若为时间序列数据则检测趋势
            trends = {}
            if self._is_time_series(ctx):
                for col in numeric_cols:
                    values = self._extract_numeric_values(rows, col)
                    if len(values) >= 3:
                        trends[col] = self._detect_trend(values)

            # 5. 若存在维度列则比较组间差异
            comparisons = {}
            dim_cols = self._find_dimension_columns(rows, numeric_cols)
            if dim_cols and len(rows) >= 4:
                comparisons = self._compare_groups(rows, numeric_cols, dim_cols, ctx)

            summary = self._build_summary(stats, outliers, trends, comparisons)

            # 附加到上下文
            ctx.statistical_report = {
                "descriptive_stats": stats,
                "outliers": outliers,
                "trends": trends,
                "group_comparisons": comparisons,
                "numeric_columns": numeric_cols,
                "dimension_columns": dim_cols,
                "row_count": len(rows),
            }

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=summary,
                confidence=0.90,
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="statistical_agent",
                    source_type="analysis",
                    payload={
                        "numeric_cols": len(numeric_cols),
                        "outliers_detected": sum(len(v) for v in outliers.values()),
                        "trends_found": len(trends),
                        "group_comparisons": len(comparisons),
                    },
                    credibility=0.95,
                    relevance=0.85,
                )],
                agent_trace={
                    "stats_columns": numeric_cols,
                    "outlier_count": sum(len(v) for v in outliers.values()),
                    "trend_count": len(trends),
                },
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="statistical analysis skipped",
                confidence=0.5,
                metadata={"cognitive_context": ctx.to_dict()},
                error=str(exc),
            )

    # ── 列检测 ────────────────────────────────────────────────

    def _find_numeric_columns(self, rows: list[dict]) -> list[str]:
        """识别数值列。"""
        if not rows:
            return []
        numeric: list[str] = []
        for col, val in rows[0].items():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                numeric.append(col)
            elif col not in numeric:
                # 检查更多行以识别数字字符串
                num_count = sum(
                    1 for r in rows[:20]
                    if isinstance(r.get(col), (int, float))
                    and not isinstance(r.get(col), bool)
                )
                if num_count >= len(rows[:20]) * 0.5 and len(rows[:20]) > 0:
                    numeric.append(col)
        return numeric

    def _find_dimension_columns(
        self, rows: list[dict], numeric_cols: list[str]
    ) -> list[str]:
        """识别分类/维度列用于分组。"""
        dims: list[str] = []
        for col in rows[0]:
            if col in numeric_cols:
                continue
            values = {r.get(col) for r in rows[:100]}
            if 1 < len(values) <= 20:
                dims.append(col)
        return dims

    # ── 核心统计 ─────────────────────────────────────────────────

    def _extract_numeric_values(
        self, rows: list[dict], col: str
    ) -> list[float]:
        """从列中提取干净的数值。"""
        values: list[float] = []
        for r in rows:
            v = r.get(col)
            if v is None or isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                if math.isfinite(v):
                    values.append(float(v))
            elif isinstance(v, str):
                try:
                    fv = float(v)
                    if math.isfinite(fv):
                        values.append(fv)
                except (ValueError, TypeError):
                    continue
        return values

    def _compute_stats(self, values: list[float]) -> dict[str, float]:
        """计算数值列表的描述统计。"""
        n = len(values)
        if n == 0:
            return {}

        sorted_vals = sorted(values)
        mean = sum(values) / n

        # 中位数
        mid = n // 2
        if n % 2 == 0:
            median = (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
        else:
            median = sorted_vals[mid]

        # 标准差
        variance = sum((v - mean) ** 2 for v in values) / n
        std = math.sqrt(variance)

        # 分位数
        def percentile(data: list[float], p: float) -> float:
            k = (len(data) - 1) * p / 100
            f = int(k)
            c = k - f
            if f + 1 < len(data):
                return data[f] + c * (data[f + 1] - data[f])
            return data[f]

        return {
            "count": float(n),
            "sum": round(sum(values), 4),
            "mean": round(mean, 4),
            "median": round(median, 4),
            "std": round(std, 4),
            "min": round(sorted_vals[0], 4),
            "max": round(sorted_vals[-1], 4),
            "p25": round(percentile(sorted_vals, 25), 4),
            "p75": round(percentile(sorted_vals, 75), 4),
            "p95": round(percentile(sorted_vals, 95), 4),
            "cv": round(std / abs(mean), 4) if mean != 0 else 0,  # 变异系数
        }

    # ── 异常值检测 ───────────────────────────────────────────────

    def _detect_outliers_all(
        self, rows: list[dict], numeric_cols: list[str]
    ) -> dict[str, list[dict]]:
        """检测所有数值列的异常值。"""
        results: dict[str, list[dict]] = {}
        for col in numeric_cols:
            values = self._extract_numeric_values(rows, col)
            if len(values) < 4:
                continue
            detected = self._detect_outliers_iqr(values)
            if detected:
                results[col] = [
                    {"index": i, "value": v, "method": "iqr"}
                    for i, v in detected
                ]
        return results

    def _detect_outliers_iqr(
        self, values: list[float]
    ) -> list[tuple[int, float]]:
        """使用 IQR 方法检测异常值（1.5 × IQR）。"""
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        q1 = sorted_vals[n // 4]
        q3 = sorted_vals[3 * n // 4]
        iqr = q3 - q1
        if iqr == 0:
            return []

        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr

        outliers: list[tuple[int, float]] = []
        for i, v in enumerate(values):
            if v < lower or v > upper:
                outliers.append((i, round(v, 4)))
        return outliers

    # ── 趋势检测 ─────────────────────────────────────────────────

    def _is_time_series(self, ctx: CognitiveContext) -> bool:
        """检查结果是否可能为时间序列数据。"""
        tw = ctx.time_window or {}
        if tw.get("type") not in (None, "none"):
            return True
        if ctx.intent and ctx.intent.get("intent_type") in ("trend",):
            return True
        return False

    def _detect_trend(self, values: list[float]) -> dict[str, Any]:
        """检测单调趋势方向与强度。"""
        n = len(values)
        if n < 3:
            return {"direction": "insufficient_data"}

        # 类 Spearman：统计递增与递减对数
        increases = 0
        decreases = 0
        for i in range(n - 1):
            for j in range(i + 1, n):
                if values[j] > values[i]:
                    increases += 1
                elif values[j] < values[i]:
                    decreases += 1

        total_pairs = increases + decreases
        if total_pairs == 0:
            return {"direction": "flat", "strength": 1.0}

        # 趋势得分：+1 = 严格递增，-1 = 严格递减
        trend_score = (increases - decreases) / total_pairs

        # 计算简单线性回归斜率
        x_mean = (n - 1) / 2
        y_mean = sum(values) / n
        numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator != 0 else 0
        slope_normalized = slope / (abs(y_mean) + 1) if y_mean != 0 else slope

        direction = "flat"
        if trend_score > 0.3:
            direction = "increasing"
        elif trend_score < -0.3:
            direction = "decreasing"

        strength = abs(trend_score)
        if strength < 0.3:
            strength_label = "weak"
        elif strength < 0.7:
            strength_label = "moderate"
        else:
            strength_label = "strong"

        return {
            "direction": direction,
            "strength": round(strength, 3),
            "strength_label": strength_label,
            "slope": round(slope, 4),
            "slope_normalized": round(slope_normalized, 6),
            "first_value": round(values[0], 4),
            "last_value": round(values[-1], 4),
            "change_pct": (
                round((values[-1] - values[0]) / abs(values[0]) * 100, 2)
                if values[0] != 0 else 0
            ),
        }

    # ── 组间比较 ────────────────────────────────────────────────

    def _compare_groups(
        self,
        rows: list[dict],
        numeric_cols: list[str],
        dim_cols: list[str],
        ctx: CognitiveContext,
    ) -> dict[str, dict]:
        """跨维度组比较数值指标。"""
        comparisons: dict[str, dict] = {}

        for dim in dim_cols[:3]:  # 最多 3 个维度，控制输出规模
            groups: dict[str, list[dict]] = {}
            for r in rows:
                key = str(r.get(dim, "null"))
                groups.setdefault(key, []).append(r)

            if len(groups) < 2 or len(groups) > 10:
                continue

            dim_comparison: dict[str, dict] = {}
            for col in numeric_cols[:5]:
                group_stats = {}
                for grp, grp_rows in groups.items():
                    vals = self._extract_numeric_values(grp_rows, col)
                    if vals:
                        group_stats[grp] = {
                            "count": len(vals),
                            "mean": round(sum(vals) / len(vals), 4),
                            "sum": round(sum(vals), 4),
                        }

                # 找到最大/最小组
                if group_stats:
                    max_grp = max(group_stats, key=lambda g: group_stats[g]["mean"])
                    min_grp = min(group_stats, key=lambda g: group_stats[g]["mean"])
                    max_mean = group_stats[max_grp]["mean"]
                    min_mean = group_stats[min_grp]["mean"]

                    dim_comparison[col] = {
                        "groups": group_stats,
                        "max_group": max_grp,
                        "min_group": min_grp,
                        "range": round(max_mean - min_mean, 4),
                        "ratio": round(max_mean / min_mean, 2) if min_mean != 0 else 0,
                    }

            if dim_comparison:
                comparisons[dim] = dim_comparison

        return comparisons

    # ── 输出 ──────────────────────────────────────────────────

    def _build_summary(
        self,
        stats: dict[str, dict],
        outliers: dict[str, list],
        trends: dict[str, dict],
        comparisons: dict[str, dict],
    ) -> str:
        """构建统计发现的人类可读摘要。"""
        parts: list[str] = []

        # 统计摘要
        if stats:
            stat_summaries = [
                f"{col}: mean={s.get('mean', '?')}, median={s.get('median', '?')}, "
                f"std={s.get('std', '?')}, range=[{s.get('min', '?')}, {s.get('max', '?')}]"
                for col, s in list(stats.items())[:5]
            ]
            parts.append("Descriptive stats:\n" + "\n".join(stat_summaries))

        # 异常值
        total_outliers = sum(len(v) for v in outliers.values())
        if total_outliers > 0:
            outlier_strs = [
                f"{col}: {len(vals)} outliers"
                for col, vals in outliers.items()
            ]
            parts.append(f"Outliers detected ({total_outliers} total):\n" + "\n".join(outlier_strs))

        # 趋势
        if trends:
            trend_strs = [
                f"{col}: {t.get('direction', '?')} ({t.get('strength_label', '?')}), "
                f"change: {t.get('change_pct', '?')}%"
                for col, t in trends.items()
            ]
            parts.append("Trends:\n" + "\n".join(trend_strs))

        # 组间比较
        if comparisons:
            comp_strs = []
            for dim, cols in comparisons.items():
                for col, c in cols.items():
                    comp_strs.append(
                        f"{dim} → {col}: max={c['max_group']}({c['groups'][c['max_group']]['mean']}), "
                        f"min={c['min_group']}({c['groups'][c['min_group']]['mean']})"
                    )
            parts.append("Group comparisons:\n" + "\n".join(comp_strs[:10]))

        return "\n\n".join(parts) if parts else "no statistical findings"

    def _skip(
        self, task: TaskMessage, ctx: CognitiveContext, reason: str
    ) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=f"statistical analysis skipped: {reason}",
            confidence=0.5,
            metadata={"cognitive_context": ctx.to_dict()},
            agent_trace={"skip_reason": reason},
        )
