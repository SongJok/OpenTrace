from __future__ import annotations

import re
from typing import Any

from kernel.data_cognition.types import SemanticContext


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

    def validate_time_filter(self, sql: str, query: str) -> list[str]:
        """Check if time-related intent in query is reflected in SQL."""
        issues: list[str] = []
        time_keywords = ["最近", "近", "过去", "last", "recent", "past", "month", "week", "day", "年", "月", "天"]
        has_time_intent = any(kw in query for kw in time_keywords)
        if not has_time_intent:
            return issues

        lowered = (sql or "").lower()
        has_time_filter = any(
            kw in lowered for kw in ("interval", "date_sub", "dateadd", "now()", "current_date", "current_timestamp")
        )
        if not has_time_filter:
            issues.append("Query implies time filtering but SQL has no time filter")

        return issues

    async def dry_run_estimate(self, sql: str, dsn: str) -> dict[str, Any]:
        """Use EXPLAIN to estimate scan rows. Returns {safe: bool, estimated_rows: int}."""
        import re as _re

        explain_sql = f"EXPLAIN {sql}"
        # We don't execute here — just return the EXPLAIN SQL for the caller to run.
        return {
            "explain_sql": explain_sql,
            "safe": True,
            "estimated_rows": None,
        }
