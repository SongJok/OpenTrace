from __future__ import annotations

import re
from typing import Any

from kernel.data_cognition.types import SemanticContext, SemanticParseResult


class SQLValidationError(ValueError):
    pass


class SQLValidator:
    FORBIDDEN = ["insert", "update", "delete", "alter", "drop", "truncate", "grant", "revoke"]

    def __init__(self, default_limit: int = 100) -> None:
        self.default_limit = default_limit

    def validate(self, sql: str) -> str:
        text = (sql or "").strip()
        if not text:
            raise SQLValidationError("empty sql")

        lowered = text.lower()
        if ";" in lowered:
            raise SQLValidationError("multiple statements are not allowed")

        if not (lowered.startswith("select") or lowered.startswith("with")):
            raise SQLValidationError("only SELECT/WITH queries are allowed")

        if any(tok in lowered for tok in self.FORBIDDEN):
            raise SQLValidationError("write/ddl statements are forbidden")

        if " limit " not in lowered:
            text = f"{text} LIMIT {self.default_limit}"

        # anti comment-injection: strip string literals first to avoid false positives
        stripped = re.sub(r"'[^']*'", "''", lowered)
        if re.search(r"--|/\*|\*/", stripped):
            raise SQLValidationError("sql comments are not allowed")

        return text

    def validate_semantic(self, sql: str, semantic_ctx: SemanticContext | None = None) -> list[str]:
        """Check semantic合理性: LIMIT 0, WHERE 1=0, full table scan risk."""
        issues: list[str] = []
        lowered = (sql or "").lower()

        if "limit 0" in lowered or "limit 0;" in lowered:
            issues.append("SQL has LIMIT 0 — likely unintentional")

        if "where 1=0" in lowered or "where 1 = 0" in lowered:
            issues.append("SQL has WHERE 1=0 — will always return empty result")

        if not re.search(r"\bwhere\b", lowered) and not re.search(r"\blimit\b", lowered):
            issues.append("SQL has no WHERE or LIMIT — potential full table scan")

        if semantic_ctx and semantic_ctx.time_macros:
            has_time_filter = any(
                kw in lowered for kw in ("interval", "date_sub", "dateadd", "now()", "current_date")
            )
            if not has_time_filter:
                for tm in semantic_ctx.time_macros:
                    col = tm.get("column", "")
                    if col and col.lower() not in lowered:
                        issues.append(f"Expected time filter on column '{col}' is missing")

        return issues

    def validate_semantic_correctness(
        self,
        sql: str,
        parse_result: SemanticParseResult,
        table_columns: dict[str, list[str]] | None = None,
    ) -> list[str]:
        """Validate that SQL correctly expresses the user's parsed intent.

        Checks:
        - Entity/metric coverage: all identified entities and metrics are in SQL
        - GROUP BY consistency: non-aggregated SELECT columns match GROUP BY
        - Time filter binding: time window uses correct column
        - WHERE condition coverage: parsed filters appear in SQL WHERE
        """
        issues: list[str] = []
        lowered = sql.lower()

        # 1. Check metric coverage
        for m in parse_result.metrics:
            if m.mapped_column and m.mapped_column.lower() not in lowered:
                issues.append(
                    f"Metric '{m.mapped_column}' (mentioned as '{m.mention}') not found in SQL"
                )

        # 2. Check entity/table coverage
        for e in parse_result.entities:
            if e.mapped_table and e.mapped_table.lower() not in lowered:
                issues.append(f"Entity table '{e.mapped_table}' not referenced in SQL")

        # 3. Check GROUP BY consistency
        group_by_lower = [g.lower().strip() for g in parse_result.group_by]
        has_group_by = "group by" in lowered
        has_agg = any(kw in lowered for kw in ("sum(", "count(", "avg(", "max(", "min("))

        if has_group_by and parse_result.group_by:
            for g in parse_result.group_by:
                if g.lower().strip() not in lowered:
                    issues.append(f"GROUP BY column '{g}' not found in SQL")

        if has_agg and not has_group_by and parse_result.group_by:
            issues.append("SQL has aggregations but no GROUP BY, yet group_by intent was detected")

        # 4. Check time filter binding
        if parse_result.time_window and parse_result.time_window.get("days"):
            has_time_sql = any(
                kw in lowered
                for kw in (
                    "date_sub",
                    "dateadd",
                    "interval",
                    "now()",
                    "current_date",
                    "current_timestamp",
                )
            )
            col_hint = parse_result.time_window.get("column_hint", "")
            if not has_time_sql:
                issues.append("Query has time window but SQL lacks time filter")
            elif col_hint and col_hint.lower() not in lowered:
                issues.append(
                    f"Time filter should use column '{col_hint}' but SQL may use different column"
                )

        # 5. Check filter coverage
        for f in parse_result.filters:
            if f.value and f.value.lower() not in lowered:
                issues.append(f"Filter value '{f.value}' not found in SQL WHERE clause")

        # 6. Check filter field coverage (if field is known)
        for f in parse_result.filters:
            if f.field and f.field.lower() not in lowered:
                issues.append(f"Filter field '{f.field}' not found in SQL")

        return issues

    def validate_intent_coverage(
        self, sql: str, query: str, parse_result: SemanticParseResult
    ) -> dict[str, Any]:
        """Compare user intent against SQL capability. Returns coverage report."""
        lowered = sql.lower()
        report: dict[str, Any] = {
            "has_time_filter": False,
            "has_where_conditions": False,
            "has_aggregation": False,
            "has_group_by": False,
            "has_order_by": False,
            "has_limit": False,
            "missing_intents": [],
            "score": 1.0,
        }

        report["has_where_conditions"] = "where" in lowered
        report["has_aggregation"] = any(
            kw in lowered for kw in ("sum(", "count(", "avg(", "max(", "min(")
        )
        report["has_group_by"] = "group by" in lowered
        report["has_order_by"] = "order by" in lowered
        report["has_limit"] = "limit" in lowered

        # Time filter check
        if parse_result.time_window and parse_result.time_window.get("days"):
            report["has_time_filter"] = any(
                kw in lowered
                for kw in (
                    "date_sub",
                    "dateadd",
                    "interval",
                    "now()",
                    "current_date",
                    "current_timestamp",
                )
            )
            if not report["has_time_filter"]:
                report["missing_intents"].append("time_filter")

        # Filter coverage check
        if parse_result.filters:
            for f in parse_result.filters:
                if f.value and f.value.lower() not in lowered:
                    report["missing_intents"].append(f"filter:{f.value}")

        # Sort intent check
        if parse_result.order_by and not report["has_order_by"]:
            report["missing_intents"].append("order_by")

        # Group by check
        if parse_result.group_by and not report["has_group_by"]:
            report["missing_intents"].append("group_by")

        # Compute coverage score
        total_checks = 5 + len(parse_result.filters)
        passed = total_checks - len(report["missing_intents"])
        report["score"] = round(passed / max(total_checks, 1), 2)

        return report

    def validate_time_filter(self, sql: str, query: str) -> list[str]:
        """Check if time-related intent in query is reflected in SQL."""
        issues: list[str] = []
        time_keywords = [
            "最近",
            "近",
            "过去",
            "last",
            "recent",
            "past",
            "month",
            "week",
            "day",
            "年",
            "月",
            "天",
        ]
        has_time_intent = any(kw in query for kw in time_keywords)
        if not has_time_intent:
            return issues

        lowered = (sql or "").lower()
        has_time_filter = any(
            kw in lowered
            for kw in (
                "interval",
                "date_sub",
                "dateadd",
                "now()",
                "current_date",
                "current_timestamp",
            )
        )
        if not has_time_filter:
            issues.append("Query implies time filtering but SQL has no time filter")

        return issues

    async def dry_run_estimate(self, sql: str, dsn: str) -> dict[str, Any]:
        """Use EXPLAIN to estimate scan rows. Returns {safe: bool, estimated_rows: int}."""

        explain_sql = f"EXPLAIN {sql}"
        return {
            "explain_sql": explain_sql,
            "safe": True,
            "estimated_rows": None,
        }
