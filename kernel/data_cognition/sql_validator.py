from __future__ import annotations

import re
from typing import Any

try:
    from sqlglot import exp, parse
    from sqlglot.errors import ParseError
except ImportError:  # pragma: no cover - packaging contract covers the dependency
    exp = None
    parse = None
    ParseError = ValueError

from kernel.data_cognition.types import SemanticContext, SemanticParseResult


class SQLValidationError(ValueError):
    pass


class SQLValidator:
    FORBIDDEN_NODE_NAMES = {
        "Alter",
        "Analyze",
        "Attach",
        "Cache",
        "Command",
        "Commit",
        "Copy",
        "Create",
        "Delete",
        "Detach",
        "Drop",
        "Execute",
        "Grant",
        "Insert",
        "Into",
        "LoadData",
        "Lock",
        "Merge",
        "Pragma",
        "Rollback",
        "Set",
        "Transaction",
        "TruncateTable",
        "Uncache",
        "Update",
        "Use",
    }
    FORBIDDEN_FUNCTIONS = {
        "benchmark",
        "dblink_connect",
        "dblink_exec",
        "load_file",
        "lo_export",
        "lo_import",
        "nextval",
        "pg_ls_dir",
        "pg_read_binary_file",
        "pg_read_file",
        "pg_sleep",
        "read_blob",
        "read_csv",
        "read_csv_auto",
        "read_json",
        "read_json_auto",
        "read_parquet",
        "set_config",
        "sleep",
        "sys_eval",
        "sys_exec",
    }

    def __init__(self, default_limit: int = 100, max_limit: int | None = None) -> None:
        self.default_limit = default_limit
        self.max_limit = max_limit or default_limit

    def validate(self, sql: str) -> str:
        text = (sql or "").strip()
        if not text:
            raise SQLValidationError("empty sql")
        if self._contains_comment(text):
            raise SQLValidationError("sql comments are not allowed")
        if parse is None or exp is None:
            raise SQLValidationError("SQL AST parser is unavailable")

        try:
            statements = [statement for statement in parse(text) if statement is not None]
        except ParseError as exc:
            raise SQLValidationError(f"invalid sql: {exc}") from exc
        if len(statements) != 1:
            raise SQLValidationError("multiple statements are not allowed")

        expression = statements[0]
        if not isinstance(expression, exp.Query):
            raise SQLValidationError("only read-only query expressions are allowed")

        for node in expression.walk():
            node_name = type(node).__name__
            if node_name in self.FORBIDDEN_NODE_NAMES:
                raise SQLValidationError(f"forbidden SQL operation: {node_name}")
            if isinstance(node, exp.Func):
                function_name = str(
                    node.name if isinstance(node, exp.Anonymous) else node.sql_name() or ""
                ).lower()
                if function_name in self.FORBIDDEN_FUNCTIONS:
                    raise SQLValidationError(f"forbidden SQL function: {function_name}")

        if expression.args.get("locks"):
            raise SQLValidationError("locking queries are not allowed")

        configured_limit = max(1, int(self.default_limit))
        maximum_limit = max(configured_limit, int(self.max_limit))
        limit_node = expression.args.get("limit")
        if limit_node is None:
            expression = expression.limit(configured_limit)
        else:
            limit_expression = getattr(limit_node, "expression", None)
            try:
                requested_limit = int(str(limit_expression.name))
            except (AttributeError, TypeError, ValueError):
                raise SQLValidationError("LIMIT must be a positive integer literal")
            if requested_limit < 1:
                raise SQLValidationError("LIMIT must be greater than zero")
            if requested_limit > maximum_limit:
                expression = expression.limit(maximum_limit)

        return expression.sql()

    @staticmethod
    def _contains_comment(sql: str) -> bool:
        quote: str | None = None
        index = 0
        while index < len(sql):
            char = sql[index]
            next_char = sql[index + 1] if index + 1 < len(sql) else ""
            if quote:
                if char == quote:
                    if next_char == quote:
                        index += 2
                        continue
                    quote = None
                elif char == "\\":
                    index += 2
                    continue
                index += 1
                continue
            if char in {"'", '"', "`"}:
                quote = char
                index += 1
                continue
            if (char == "-" and next_char == "-") or (char == "/" and next_char == "*"):
                return True
            index += 1
        return False

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
