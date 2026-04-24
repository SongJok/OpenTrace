from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway
from kernel.data_cognition.sql_dialect import SQLDialectSpec


@dataclass
class RewriteAttempt:
    """Record of a single SQL rewrite attempt."""
    attempt_num: int
    original_sql: str
    error: str
    rewritten_sql: str | None
    success: bool
    timestamp: float = field(default_factory=lambda: __import__('time').time())


class SQLRewriter:
    """
    SQL Rewriter with retry tracking and enhanced error context.
    
    When rewrites fail repeatedly, preserves error history for user-facing recovery options.
    """
    
    MAX_REWRITE_ATTEMPTS = 2

    def __init__(self, trace_id: str | None = None):
        self.trace_id = trace_id or str(uuid.uuid4())[:8]
        self.attempts: list[RewriteAttempt] = []

    async def rewrite(
        self, 
        sql: str, 
        error: str, 
        schema_hint: str = "", 
        dialect: SQLDialectSpec | None = None,
        attempt_num: int = 1,
    ) -> tuple[str | None, list[RewriteAttempt]]:
        """
        Rewrite SQL based on error feedback.
        
        Returns:
            tuple: (rewritten_sql or None, list of all rewrite attempts for context)
        """
        dialect_name = dialect.name if dialect else 'generic'
        prompt = (
            "You are a SQL repair assistant. Fix the SQL based on error and schema. "
            "Return only a single corrected SQL statement, read-only, with LIMIT. "
            f"Target dialect: {dialect_name}."
        )
        user = f"SQL: {sql}\nError: {error}\nSchema hint: {schema_hint}\nDialect: {dialect_name}"
        
        rewritten_sql: str | None = None
        success = False
        
        try:
            gw = get_model_gateway()
            resp = await gw.complete(
                messages=[
                    LLMMessage(role="system", content=prompt),
                    LLMMessage(role="user", content=user),
                ],
                role=LLMRole.PLANNING,
                temperature=0.0,
                max_tokens=300,
            )
            raw = (resp.content or "").strip()
            # Clean markdown code fences
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            raw = raw.strip("`").strip()
            # Validate: must be non-empty and start with SELECT or WITH
            if raw and raw.lower().startswith(("select", "with")):
                rewritten_sql = raw
                success = True
        except Exception as e:
            # Log the exception but don't fail the whole flow
            pass
        
        # Record this attempt
        attempt = RewriteAttempt(
            attempt_num=attempt_num,
            original_sql=sql,
            error=error,
            rewritten_sql=rewritten_sql,
            success=success,
        )
        self.attempts.append(attempt)
        
        return rewritten_sql, self.attempts

    def get_recovery_context(self) -> dict[str, Any]:
        """
        Generate structured context for user-facing error recovery options.
        
        Returns dict with:
        - trace_id: for admin support
        - error_history: list of errors encountered
        - suggestions: user-facing recovery options
        """
        if not self.attempts:
            return {"trace_id": self.trace_id, "error_history": [], "suggestions": []}
        
        # Extract unique errors
        errors = [a.error for a in self.attempts if a.error]
        unique_errors = list(dict.fromkeys(errors))  # Preserve order, remove duplicates
        
        # Generate recovery suggestions based on error patterns
        suggestions = []
        last_error = unique_errors[-1].lower() if unique_errors else ""
        
        if "syntax" in last_error or "parse" in last_error:
            suggestions.append({
                "action": "manual_fix",
                "label": "手动修正 SQL",
                "description": "语法错误，可手动调整查询语句",
                "hint": "检查括号匹配、关键字拼写、表名/列名引用",
            })
        elif "permission" in last_error or "access denied" in last_error:
            suggestions.append({
                "action": "contact_admin",
                "label": "联系管理员",
                "description": "权限不足，需要管理员协助",
                "hint": "请提供 trace_id 以便快速定位问题",
            })
        elif "connection" in last_error or "timeout" in last_error:
            suggestions.append({
                "action": "retry_later",
                "label": "稍后重试",
                "description": "数据库连接问题，请稍后重试",
                "hint": "检查数据库服务状态或网络连通性",
            })
        elif "column" in last_error or "table" in last_error:
            suggestions.append({
                "action": "manual_fix",
                "label": "手动修正 SQL",
                "description": "表或列不存在，可手动调整引用",
                "hint": "确认表名/列名拼写，或检查数据库结构",
            })
        else:
            # Generic fallback suggestions
            suggestions.append({
                "action": "manual_fix",
                "label": "手动修正 SQL",
                "description": "查询执行失败，可手动调整",
            })
            suggestions.append({
                "action": "contact_admin",
                "label": "联系管理员",
                "description": "如需技术支持，请联系管理员",
            })
        
        return {
            "trace_id": self.trace_id,
            "error_history": unique_errors,
            "suggestions": suggestions,
            "attempt_count": len(self.attempts),
            "last_sql": self.attempts[-1].original_sql if self.attempts else "",
        }
