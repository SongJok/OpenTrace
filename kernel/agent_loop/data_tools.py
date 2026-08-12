"""Responses 主链路中的 DataAgent 受治理执行能力。"""

from __future__ import annotations

from typing import Any

from kernel.agent_loop.contracts import SideEffect, ToolSpec


def governed_sql_execution_spec() -> ToolSpec:
    """只暴露持久草案执行，不引入遗留通用工具注册表。"""

    return ToolSpec(
        name="execute_sql_draft",
        description=(
            "执行已经向用户展示并由用户明确选择的持久化 SQL 草案候选。"
            "首次问数不得调用；执行前重新校验权限、Schema、语义、SQL 哈希、"
            "只读 AST 和 EXPLAIN，并进入 Responses 持久审批。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "已展示的 SQL 草案 ID"},
                "candidate_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "用户明确选择的候选 ID；执行全部时为空",
                },
                "execute_all": {
                    "type": "boolean",
                    "description": "仅当用户明确要求执行全部候选时为 true",
                },
                "retry_failed": {
                    "type": "boolean",
                    "description": "仅当用户明确要求重试失败候选时为 true",
                },
            },
            "required": ["draft_id", "candidate_ids", "execute_all", "retry_failed"],
            "additionalProperties": False,
        },
        side_effect=SideEffect.WRITE,
        timeout_seconds=60.0,
        max_retries=0,
        supports_parallel=False,
    )


async def execute_governed_sql_draft(
    *,
    response: Any,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """使用服务端 Response Scope 执行已确认草案，忽略模型提供的身份字段。"""

    from infra.storage.database import AsyncSessionLocal
    from services.sql_assets import execute_sql_query_draft

    async with AsyncSessionLocal() as db:
        return await execute_sql_query_draft(
            db,
            draft_id=str(arguments.get("draft_id") or ""),
            user_id=response.user_id,
            tenant_id=response.tenant_id,
            workspace_id=response.workspace_id,
            candidate_ids=[str(item) for item in arguments.get("candidate_ids") or [] if str(item)],
            execute_all=bool(arguments.get("execute_all")),
            retry_failed=bool(arguments.get("retry_failed")),
        )
