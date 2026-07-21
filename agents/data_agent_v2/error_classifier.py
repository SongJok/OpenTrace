"""
ErrorClassifier — 独立错误诊断与修复策略引擎。

将数据查询失败归类为可执行类别并给出针对性修复策略；
与 ReflectionAgent、SQLRewriter 组成：分类 → 诊断 → 修复 → 校验 闭环。

错误分类：
  SQL：语法、列/表不存在、权限、连接
  逻辑：JOIN 放大、缺 JOIN、错误键、时间过严/过宽、指标公式等
  数据质量：空结果、空值过多、负指标、离群
  语义：实体歧义、别名未解析、模式漂移

每类对应 repair_strategy，指导 SQLRewriter 提示词。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErrorCategory(str, Enum):
    """顶层错误类别。"""
    SQL_SYNTAX = "sql_syntax"
    SQL_COLUMN_NOT_FOUND = "sql_column_not_found"
    SQL_TABLE_NOT_FOUND = "sql_table_not_found"
    SQL_PERMISSION = "sql_permission"
    SQL_CONNECTION = "sql_connection"

    JOIN_AMPLIFICATION = "join_amplification"
    MISSING_JOIN = "missing_join"
    WRONG_JOIN_KEY = "wrong_join_key"

    TIME_TOO_RESTRICTIVE = "time_too_restrictive"
    TIME_TOO_BROAD = "time_too_broad"
    TIME_FORMAT_ERROR = "time_format_error"

    METRIC_WRONG_FORMULA = "metric_wrong_formula"
    METRIC_MISSING_AGG = "metric_missing_agg"
    METRIC_WRONG_COLUMN = "metric_wrong_column"

    FILTER_OVER_RESTRICTIVE = "filter_over_restrictive"
    FILTER_CONTRADICTORY = "filter_contradictory"
    FILTER_MISSING = "filter_missing"

    EMPTY_RESULT = "empty_result"
    NULL_HEAVY = "null_heavy"
    NEGATIVE_METRICS = "negative_metrics"
    OUTLIER_VALUES = "outlier_values"

    AMBIGUOUS_ENTITY = "ambiguous_entity"
    UNRESOLVED_ALIAS = "unresolved_alias"
    SCHEMA_DRIFT = "schema_drift"


@dataclass
class ErrorDiagnosis:
    """单个检测问题的结构化诊断。"""
    category: ErrorCategory
    severity: str  # critical / high / medium / low
    description: str
    evidence: list[str] = field(default_factory=list)
    repair_strategy: str = ""
    repair_guidance: str = ""
    repairable: bool = True


DEFAULT_REPAIR_STRATEGIES: dict[ErrorCategory, dict[str, str]] = {
    # ── SQL 错误 ─────────────────────────────────────────────────
    ErrorCategory.SQL_SYNTAX: {
        "strategy": "fix_syntax",
        "guidance": (
            "Check SQL syntax: parentheses matching, keyword spelling, "
            "quote usage, comma placement. Rewrite with correct syntax."
        ),
        "repairable": "true",
    },
    ErrorCategory.SQL_COLUMN_NOT_FOUND: {
        "strategy": "replace_column",
        "guidance": (
            "Replace invalid column name with the closest match from "
            "available schema. Use fuzzy matching on column names. "
            "If no match found, remove the column from the query."
        ),
        "repairable": "true",
    },
    ErrorCategory.SQL_TABLE_NOT_FOUND: {
        "strategy": "replace_table",
        "guidance": (
            "Replace invalid table name with the closest match from "
            "available schema. Check plural/singular forms and abbreviations."
        ),
        "repairable": "true",
    },
    ErrorCategory.SQL_PERMISSION: {
        "strategy": "cannot_repair",
        "guidance": "Permission denied. Cannot repair automatically — user must contact admin.",
        "repairable": "false",
    },
    ErrorCategory.SQL_CONNECTION: {
        "strategy": "retry_with_backoff",
        "guidance": "Connection error. Retry with exponential backoff (1s, 2s, 4s).",
        "repairable": "true",
    },

    # ── JOIN 错误 ────────────────────────────────────────────────
    ErrorCategory.JOIN_AMPLIFICATION: {
        "strategy": "add_distinct_or_fix_join",
        "guidance": (
            "Detected cartesian product or join amplification. "
            "1) Check if any join creates N:M without dedup. "
            "2) Add DISTINCT or pre-aggregate the many-side before joining. "
            "3) Verify join keys match actual foreign key relationships."
        ),
        "repairable": "true",
    },
    ErrorCategory.MISSING_JOIN: {
        "strategy": "add_join",
        "guidance": (
            "Query references columns from multiple tables but JOIN is missing. "
            "Add the necessary JOIN condition using verified foreign key relationships."
        ),
        "repairable": "true",
    },
    ErrorCategory.WRONG_JOIN_KEY: {
        "strategy": "fix_join_key",
        "guidance": (
            "JOIN condition references wrong column pair. "
            "Use verified foreign key from table_relationships. "
            "Common fix: replace plural table.column → singular table.column (e.g., orders.user_id vs order.user_id)."
        ),
        "repairable": "true",
    },

    # ── 时间错误 ─────────────────────────────────────────────────
    ErrorCategory.TIME_TOO_RESTRICTIVE: {
        "strategy": "widen_time_window",
        "guidance": (
            "Time filter may be too restrictive causing 0 results. "
            "Try widening the time range: remove end date, "
            "use a broader range (e.g., last 90 days instead of last 7 days), "
            "or remove the time filter entirely for diagnostic purposes."
        ),
        "repairable": "true",
    },
    ErrorCategory.TIME_TOO_BROAD: {
        "strategy": "narrow_time_window",
        "guidance": (
            "Time filter is too broad — query may be slow or return too much data. "
            "Add a reasonable default range (e.g., last 30 days) or apply LIMIT."
        ),
        "repairable": "true",
    },
    ErrorCategory.TIME_FORMAT_ERROR: {
        "strategy": "fix_time_format",
        "guidance": (
            "Time filter format is incorrect. Check: "
            "1) Date string format matches column type (e.g., 'YYYY-MM-DD' for DATE). "
            "2) Timestamp comparisons use correct cast. "
            "3) Relative date expressions match dialect syntax."
        ),
        "repairable": "true",
    },

    # ── 指标错误 ───────────────────────────────────────────────
    ErrorCategory.METRIC_WRONG_FORMULA: {
        "strategy": "fix_metric_formula",
        "guidance": (
            "Metric formula does not match authoritative definition in metric_definitions. "
            "Replace with the exact formula from metric_definitions.formula. "
            "Pay attention to FILTER clauses, CASE WHEN conditions, and NULL handling."
        ),
        "repairable": "true",
    },
    ErrorCategory.METRIC_MISSING_AGG: {
        "strategy": "add_aggregation",
        "guidance": (
            "Metric column is used without aggregation function. "
            "Add the appropriate aggregate (SUM/COUNT/AVG/MAX/MIN) "
            "and ensure GROUP BY includes all non-aggregated columns."
        ),
        "repairable": "true",
    },
    ErrorCategory.METRIC_WRONG_COLUMN: {
        "strategy": "replace_metric_column",
        "guidance": (
            "Metric references wrong column. "
            "Replace with the correct underlying column from metric_definitions. "
            "Check column aliases and formula column references."
        ),
        "repairable": "true",
    },

    # ── 筛选器错误 ───────────────────────────────────────────────
    ErrorCategory.FILTER_OVER_RESTRICTIVE: {
        "strategy": "relax_filters",
        "guidance": (
            "Filters are too restrictive — query returns 0 rows. "
            "Try: removing optional filters, using OR instead of AND, "
            "expanding value ranges, or removing entity-specific filters."
        ),
        "repairable": "true",
    },
    ErrorCategory.FILTER_CONTRADICTORY: {
        "strategy": "resolve_contradiction",
        "guidance": (
            "Filters contain contradictory conditions (e.g., status='active' AND status='inactive'). "
            "Remove the contradictory condition or use OR."
        ),
        "repairable": "true",
    },
    ErrorCategory.FILTER_MISSING: {
        "strategy": "add_filter",
        "guidance": (
            "Query is missing a filter that would make results more relevant. "
            "Add entity-specific filter, status filter (exclude deleted/cancelled), "
            "or date range filter."
        ),
        "repairable": "true",
    },

    # ── 数据质量 ────────────────────────────────────────────────
    ErrorCategory.EMPTY_RESULT: {
        "strategy": "diagnose_then_relax",
        "guidance": (
            "Query returned 0 rows. Step-by-step diagnosis: "
            "1) Check if time window eliminates all data — try without time filter. "
            "2) Check if entity filters are too narrow — try removing one filter at a time. "
            "3) Check if metric references non-existent combinations. "
            "4) Consider adding 'OR <column> IS NULL' for optional filters."
        ),
        "repairable": "true",
    },
    ErrorCategory.NULL_HEAVY: {
        "strategy": "add_null_handling",
        "guidance": (
            "Many NULL values in results. Consider: "
            "1) COALESCE(column, default_value) for display. "
            "2) LEFT JOIN → INNER JOIN if NULLs are unwanted. "
            "3) Add 'WHERE column IS NOT NULL' if appropriate."
        ),
        "repairable": "true",
    },
    ErrorCategory.NEGATIVE_METRICS: {
        "strategy": "fix_metric_grounding",
        "guidance": (
            "Metric returned negative values where positive expected. "
            "1) Check if metric formula handles refunds/returns correctly. "
            "2) Verify JOIN direction (are we counting from the right table?). "
            "3) Consider ABS() or CASE WHEN value < 0 THEN 0 ELSE value END."
        ),
        "repairable": "true",
    },
    ErrorCategory.OUTLIER_VALUES: {
        "strategy": "add_validation_filter",
        "guidance": (
            "Result contains outlier values (extremely large/small). "
            "1) Check for cartesian product (see join_amplification). "
            "2) Add WHERE value < threshold for known outliers. "
            "3) Use PERCENTILE or IQR-based filtering for robust analysis."
        ),
        "repairable": "true",
    },

    # ── 语义错误 ─────────────────────────────────────────────
    ErrorCategory.AMBIGUOUS_ENTITY: {
        "strategy": "disambiguate_entity",
        "guidance": (
            "Entity reference is ambiguous — multiple tables match. "
            "Use the most specific match based on metric context. "
            "Prefer verified relationships and higher usage_count tables."
        ),
        "repairable": "true",
    },
    ErrorCategory.UNRESOLVED_ALIAS: {
        "strategy": "resolve_alias",
        "guidance": (
            "Column alias or metric name could not be resolved to a physical column. "
            "Check schema_metadata.business_name for matches. "
            "Use available schema columns only."
        ),
        "repairable": "true",
    },
    ErrorCategory.SCHEMA_DRIFT: {
        "strategy": "notify_drift",
        "guidance": (
            "Schema has changed since knowledge was last indexed. "
            "Trigger schema re-sync and use fallback heuristic path."
        ),
        "repairable": "false",
    },
}


class ErrorClassifier:
    """将查询错误和结果质量问题分类为可执行的类别。

    为每个分类错误提供修复策略和指导，
    供 ReflectionAgent 定向修复，以及 Supervisor 生成面向用户的恢复建议。

    策略从两层加载：
    1. DEFAULT_REPAIR_STRATEGIES（内置代码默认值）
    2. repair_strategies.json（可选覆盖层，以 ErrorCategory 值为键）
    JSON 覆盖层按键覆盖；未知键会被添加而非拒绝。
    """

    def __init__(self, config_path: str | None = None) -> None:
        self._strategies: dict[ErrorCategory, dict[str, str]] = dict(DEFAULT_REPAIR_STRATEGIES)
        path = config_path
        if not path:
            try:
                from infra.config.settings import settings
                path = getattr(settings, "data_agent_v2_repair_strategies_path", "") or ""
            except Exception:
                path = ""
        if path and os.path.isfile(path):
            try:
                with open(path) as f:
                    custom = json.load(f)
                for k, v in custom.items():
                    if k.startswith("_"):
                        continue
                    try:
                        cat = ErrorCategory(k)
                        self._strategies[cat] = {**self._strategies.get(cat, {}), **v}
                    except ValueError:
                        pass
            except Exception:
                pass

    def classify_sql_error(self, error_message: str) -> ErrorDiagnosis:
        """对 SQL 执行错误消息进行分类。"""
        err = error_message.lower()

        if any(kw in err for kw in ("syntax", "parse", "unexpected", "expecting")):
            return self._build_diagnosis(ErrorCategory.SQL_SYNTAX, error_message)

        if any(kw in err for kw in ("column", "field", "unknown column", "does not exist")
        ) and ("table" not in err or "column" in err):
            return self._build_diagnosis(ErrorCategory.SQL_COLUMN_NOT_FOUND, error_message)

        if any(kw in err for kw in ("table", "relation", "doesn't exist", "not exist")):
            return self._build_diagnosis(ErrorCategory.SQL_TABLE_NOT_FOUND, error_message)

        if any(kw in err for kw in ("permission", "access denied", "privilege", "forbidden")):
            return self._build_diagnosis(ErrorCategory.SQL_PERMISSION, error_message)

        if any(kw in err for kw in ("connection", "timeout", "refused", "unreachable")):
            return self._build_diagnosis(ErrorCategory.SQL_CONNECTION, error_message)

        if any(kw in err for kw in ("aggregate", "group by", "not in group by")):
            return self._build_diagnosis(ErrorCategory.METRIC_MISSING_AGG, error_message)

        # 默认：通用语法错误
        return self._build_diagnosis(ErrorCategory.SQL_SYNTAX, error_message)

    def classify_result_quality(
        self,
        rows: list[dict],
        row_count: int,
        join_count: int = 0,
        metrics: list[dict] | None = None,
        error: str = "",
    ) -> list[ErrorDiagnosis]:
        """对已执行查询的结果质量问题进行分类。"""
        diagnoses: list[ErrorDiagnosis] = []

        if not rows and not error:
            diagnoses.append(self._build_diagnosis(
                ErrorCategory.EMPTY_RESULT,
                "Query returned 0 rows — possible over-filtering or no matching data",
            ))

        if not rows:
            return diagnoses

        first_row = rows[0]

        # NULL 值过多检查
        if first_row:
            null_count = sum(1 for v in first_row.values() if v is None)
            total_cols = len(first_row)
            if total_cols > 0 and null_count / total_cols > 0.4:
                diagnoses.append(self._build_diagnosis(
                    ErrorCategory.NULL_HEAVY,
                    f"{null_count}/{total_cols} columns in first row are NULL",
                ))

        # 负指标检查
        if metrics and first_row:
            metric_cols = {m.get("mapped_column", "") for m in metrics}
            for col, val in first_row.items():
                if isinstance(val, (int, float)) and val < 0:
                    is_metric = any(col.endswith(mc) or mc.endswith(col) for mc in metric_cols)
                    if is_metric:
                        diagnoses.append(self._build_diagnosis(
                            ErrorCategory.NEGATIVE_METRICS,
                            f"Metric column '{col}' = {val} (negative)",
                        ))

        # 离群值 / JOIN 放大检查
        if first_row:
            for col, val in first_row.items():
                if isinstance(val, (int, float)) and val > 1_000_000_000:
                    diagnoses.append(self._build_diagnosis(
                        ErrorCategory.OUTLIER_VALUES if join_count <= 1
                        else ErrorCategory.JOIN_AMPLIFICATION,
                        f"Column '{col}' = {val} (extremely large)",
                    ))

        # 大结果集且多 JOIN
        if row_count > 1000 and join_count > 1:
            diagnoses.append(self._build_diagnosis(
                ErrorCategory.JOIN_AMPLIFICATION,
                f"Large result ({row_count} rows) with {join_count} joins",
            ))

        return diagnoses

    def classify_runtime_issue(
        self,
        rows: list[dict],
        error: str,
        verification_report: dict | None,
        ctx,  # CognitiveContext
    ) -> list[ErrorDiagnosis]:
        """完整分类：SQL 错误 + 结果质量 + 语义问题。"""
        diagnoses: list[ErrorDiagnosis] = []

        # 1. SQL 错误
        if error:
            diagnoses.append(self.classify_sql_error(error))

        # 2. 结果质量
        join_count = len(ctx.join_paths or [])
        quality_diags = self.classify_result_quality(
            rows=rows,
            row_count=len(rows),
            join_count=join_count,
            metrics=ctx.metrics,
            error=error,
        )
        diagnoses.extend(quality_diags)

        # 3. 验证失败
        if verification_report and verification_report.get("status") == "fail":
            for issue in verification_report.get("issues", []):
                detail = issue.get("detail", "")
                check = issue.get("check", "")
                if "metric" in (check + detail).lower():
                    diagnoses.append(self._build_diagnosis(
                        ErrorCategory.METRIC_WRONG_FORMULA, detail
                    ))
                elif "table" in (check + detail).lower() or "entity" in (check + detail).lower():
                    diagnoses.append(self._build_diagnosis(
                        ErrorCategory.AMBIGUOUS_ENTITY, detail
                    ))
                elif "time" in (check + detail).lower():
                    diagnoses.append(self._build_diagnosis(
                        ErrorCategory.TIME_TOO_RESTRICTIVE, detail
                    ))
                else:
                    diagnoses.append(self._build_diagnosis(
                        ErrorCategory.SCHEMA_DRIFT, detail
                    ))

        # 4. 基于上下文的检查
        if not rows and not error:
            tw = ctx.time_window or {}
            if tw.get("type") not in (None, "none") and tw.get("days", 0) > 0:
                diagnoses.append(self._build_diagnosis(
                    ErrorCategory.TIME_TOO_RESTRICTIVE,
                    f"Time window '{tw.get('description', '')}' may be too restrictive",
                ))
            if ctx.entities and len(ctx.entities) > 0:
                diagnoses.append(self._build_diagnosis(
                    ErrorCategory.FILTER_OVER_RESTRICTIVE,
                    f"Entity filters on {len(ctx.entities)} entities may be too narrow",
                ))

        return diagnoses

    def get_repair_prompt(
        self, diagnoses: list[ErrorDiagnosis]
    ) -> str:
        """从所有诊断构建组合修复提示。"""
        if not diagnoses:
            return ""

        repairable = [d for d in diagnoses if d.repairable]
        if not repairable:
            return ""

        parts: list[str] = []
        for d in repairable[:4]:  # 上限 4 条，保持提示聚焦
            parts.append(
                f"- [{d.category.value}] ({d.severity}) {d.description}\n"
                f"  Strategy: {d.repair_strategy}\n"
                f"  Guidance: {d.repair_guidance}"
            )

        header = (
            "Apply the following repairs to the SQL query. "
            "Each repair is listed with its category, strategy, and specific guidance:\n\n"
        )
        return header + "\n".join(parts)

    def get_recovery_suggestions(
        self, diagnoses: list[ErrorDiagnosis]
    ) -> list[dict[str, str]]:
        """从诊断结果构建面向用户的恢复建议。"""
        suggestions: list[dict[str, str]] = []

        for d in diagnoses:
            if d.category in (ErrorCategory.SQL_PERMISSION,):
                suggestions.append({
                    "action": "contact_admin",
                    "label": "联系管理员",
                    "description": "权限不足，需要管理员授予相应数据库权限",
                })
            elif d.category in (ErrorCategory.SQL_CONNECTION,):
                suggestions.append({
                    "action": "retry_later",
                    "label": "稍后重试",
                    "description": "数据库连接异常，请稍后重试",
                })
            elif d.category in (ErrorCategory.SCHEMA_DRIFT,):
                suggestions.append({
                    "action": "resync_schema",
                    "label": "重新同步 Schema",
                    "description": "数据结构可能已变更，建议重新同步数据源",
                })
            elif d.repairable:
                suggestions.append({
                    "action": "manual_fix",
                    "label": "手动修正查询",
                    "description": f"{d.category.value}: {d.description[:100]}",
                })

        if not suggestions:
            suggestions.append({
                "action": "contact_admin",
                "label": "联系管理员",
                "description": "查询执行异常，请查看详细日志",
            })

        return suggestions

    def _build_diagnosis(
        self,
        category: ErrorCategory,
        description: str,
    ) -> ErrorDiagnosis:
        strategy_info = self._strategies.get(category, {})
        severity = self._category_severity(category)
        return ErrorDiagnosis(
            category=category,
            severity=severity,
            description=description,
            evidence=[description],
            repair_strategy=strategy_info.get("strategy", "unknown"),
            repair_guidance=strategy_info.get("guidance", ""),
            repairable=strategy_info.get("repairable", "true") == "true",
        )

    @staticmethod
    def _category_severity(category: ErrorCategory) -> str:
        if category in (ErrorCategory.SQL_SYNTAX, ErrorCategory.SQL_CONNECTION):
            return "critical"
        if category in (
            ErrorCategory.SQL_COLUMN_NOT_FOUND,
            ErrorCategory.SQL_TABLE_NOT_FOUND,
            ErrorCategory.JOIN_AMPLIFICATION,
            ErrorCategory.METRIC_WRONG_FORMULA,
        ):
            return "high"
        if category in (
            ErrorCategory.TIME_TOO_RESTRICTIVE,
            ErrorCategory.FILTER_OVER_RESTRICTIVE,
            ErrorCategory.NEGATIVE_METRICS,
            ErrorCategory.NULL_HEAVY,
        ):
            return "medium"
        return "low"
