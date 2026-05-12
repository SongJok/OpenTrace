from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from kernel.data_cognition.sql_dialect import SQLDialectSpec
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway


@dataclass
class RewriteAttempt:
    """Record of a single SQL rewrite attempt."""

    attempt_num: int
    original_sql: str
    error: str
    rewritten_sql: str | None
    success: bool
    error_category: str = ""
    timestamp: float = field(default_factory=lambda: __import__("time").time())


class SQLRewriter:
    """
    SQL Rewriter with error-pattern classification, schema-guided repair,
    and retry tracking for user-facing recovery options.
    """

    MAX_REWRITE_ATTEMPTS = 2

    def __init__(self, trace_id: str | None = None):
        self.trace_id = trace_id or str(uuid.uuid4())[:8]
        self.attempts: list[RewriteAttempt] = []

    @staticmethod
    def classify_error(error: str) -> str:
        """Classify error into categories for targeted repair."""
        err = error.lower()
        if any(kw in err for kw in ("syntax", "parse", "unexpected", "expecting")):
            return "syntax"
        if any(kw in err for kw in ("column", "field", "unknown column")):
            return "column"
        if any(kw in err for kw in ("table", "doesn't exist", "not exist")):
            return "table"
        if any(kw in err for kw in ("join", "on clause", "ambiguous")):
            return "join"
        if any(kw in err for kw in ("permission", "access denied", "privilege")):
            return "permission"
        if any(kw in err for kw in ("connection", "timeout", "refused")):
            return "connection"
        if any(kw in err for kw in ("aggregate", "group by", "not in group by")):
            return "aggregation"
        return "general"

    async def rewrite(
        self,
        sql: str,
        error: str,
        schema_hint: str = "",
        dialect: SQLDialectSpec | None = None,
        attempt_num: int = 1,
        parse_context: str = "",
    ) -> str | None:
        """
        Rewrite SQL based on error feedback with schema-guided repair.

        Returns:
            rewritten_sql or None if repair failed.
        """
        dialect_name = dialect.name if dialect else "generic"
        error_cat = self.classify_error(error)

        category_guidance = {
            "syntax": "Fix SQL syntax errors: check parentheses, keywords, string quotes, and comma placement.",
            "column": "Replace invalid column names with valid alternatives from the schema. Use only columns listed in Available schema.",
            "table": "Replace invalid table names with valid ones from Available schema. Only reference tables that exist.",
            "join": "Fix JOIN conditions: ensure ON clause references columns from both tables. Use valid foreign key relationships.",
            "aggregation": "Fix GROUP BY: all non-aggregated columns in SELECT must appear in GROUP BY clause.",
            "permission": "Cannot fix permission errors. Return the same SQL unchanged.",
            "connection": "Cannot fix connection errors. Return the same SQL unchanged.",
            "general": "Fix the SQL based on the error message. Ensure the result is a valid SELECT statement.",
        }

        schema_info = ""
        if schema_hint:
            schema_info = f"\nAvailable schema:\n{schema_hint}"
        if parse_context:
            schema_info += f"\nQuery context: {parse_context}"

        prompt = (
            f"You are a SQL repair assistant. {category_guidance.get(error_cat, category_guidance['general'])}\n"
            f"Target dialect: {dialect_name}.\n"
            "Rules: return ONLY a single corrected SQL statement (read-only, SELECT). No explanation. No markdown.\n"
            f"{schema_info}"
        )
        user_msg = f"SQL:\n{sql}\n\nError:\n{error}"

        rewritten_sql: str | None = None

        try:
            gw = get_model_gateway()
            resp = await gw.complete(
                messages=[
                    LLMMessage(role="system", content=prompt),
                    LLMMessage(role="user", content=user_msg),
                ],
                role=LLMRole.PLANNING,
                temperature=0.0,
                max_tokens=400,
            )
            raw = (resp.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            raw = raw.strip("`").strip()

            if raw and raw.lower().startswith(("select", "with")):
                rewritten_sql = raw
        except Exception:
            pass

        attempt = RewriteAttempt(
            attempt_num=attempt_num,
            original_sql=sql,
            error=error,
            rewritten_sql=rewritten_sql,
            success=rewritten_sql is not None,
            error_category=error_cat,
        )
        self.attempts.append(attempt)

        return rewritten_sql

    def get_recovery_context(self) -> dict[str, Any]:
        """Generate structured context for user-facing error recovery options."""
        if not self.attempts:
            return {"trace_id": self.trace_id, "error_history": [], "suggestions": []}

        errors = [a.error for a in self.attempts if a.error]
        unique_errors = list(dict.fromkeys(errors))

        suggestions = []
        last_error = unique_errors[-1].lower() if unique_errors else ""

        if "syntax" in last_error or "parse" in last_error:
            suggestions.append(
                {
                    "action": "manual_fix",
                    "label": "手动修正 SQL",
                    "description": "语法错误，可手动调整查询语句",
                    "hint": "检查括号匹配、关键字拼写、表名/列名引用",
                }
            )
        elif "permission" in last_error or "access denied" in last_error:
            suggestions.append(
                {
                    "action": "contact_admin",
                    "label": "联系管理员",
                    "description": "权限不足，需要管理员协助",
                    "hint": "请提供 trace_id 以便快速定位问题",
                }
            )
        elif "connection" in last_error or "timeout" in last_error:
            suggestions.append(
                {
                    "action": "retry_later",
                    "label": "稍后重试",
                    "description": "数据库连接问题，请稍后重试",
                    "hint": "检查数据库服务状态或网络连通性",
                }
            )
        elif "column" in last_error or "table" in last_error:
            suggestions.append(
                {
                    "action": "manual_fix",
                    "label": "手动修正 SQL",
                    "description": "表或列不存在，可手动调整引用",
                    "hint": "确认表名/列名拼写，或检查数据库结构",
                }
            )
        else:
            suggestions.append(
                {
                    "action": "manual_fix",
                    "label": "手动修正 SQL",
                    "description": "查询执行失败，可手动调整",
                }
            )
            suggestions.append(
                {
                    "action": "contact_admin",
                    "label": "联系管理员",
                    "description": "如需技术支持，请联系管理员",
                }
            )

        return {
            "trace_id": self.trace_id,
            "error_history": unique_errors,
            "suggestions": suggestions,
            "attempt_count": len(self.attempts),
            "last_sql": self.attempts[-1].original_sql if self.attempts else "",
        }
