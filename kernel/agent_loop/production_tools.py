"""Responses 主路径中的审批后生产操作工具。"""

from __future__ import annotations

from typing import Any

from kernel.agent_loop.contracts import SideEffect, ToolSpec


def governed_production_action_spec() -> ToolSpec:
    return ToolSpec(
        name="execute_production_action",
        description=(
            "仅执行 Production Agent 刚返回的 action_ref。该动作会修改外部生产状态，"
            "必须进入 Responses 持久审批；不得自行构造连接器、操作、资产、环境或原始参数。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action_ref": {
                    "type": "string",
                    "description": "Production Agent 动作目录中的原样 action_ref",
                },
                "justification": {
                    "type": "string",
                    "description": "基于证据的执行理由，不得包含凭据或未经验证的事实",
                },
                "expected_outcome": {
                    "type": "string",
                    "description": "执行后需要验证的预期结果",
                },
            },
            "required": ["action_ref", "justification", "expected_outcome"],
            "additionalProperties": False,
        },
        side_effect=SideEffect.DESTRUCTIVE,
        operation_class="production_change",
        timeout_seconds=120.0,
        max_retries=0,
        supports_parallel=False,
    )


async def execute_governed_production_action(
    *, response: Any, arguments: dict[str, Any]
) -> dict[str, Any]:
    """从 Response 可信范围重新解析动作，忽略模型提供的身份和执行参数。"""

    from sqlalchemy import select

    from infra.storage.database import AsyncSessionLocal
    from infra.storage.models import ResponseToolExecution, User
    from services.production_intelligence.actions import execute_production_action
    from services.production_intelligence.asset_graph import ProductionScope
    from tenant.tenant_rls import set_session_scope

    async with AsyncSessionLocal() as db:
        await set_session_scope(
            db, tenant_id=response.tenant_id, workspace_id=response.workspace_id
        )
        user = await db.scalar(
            select(User).where(User.id == response.user_id, User.is_active.is_(True))
        )
        if user is None:
            return {"status": "failed", "error": "production_action_user_not_authorized"}
        action_ref = str(arguments.get("action_ref") or "")
        rows = await db.execute(
            select(ResponseToolExecution.result).where(
                ResponseToolExecution.response_id == response.id,
                ResponseToolExecution.tool_name == "production",
                ResponseToolExecution.status == "completed",
            )
        )
        catalogued = False
        for raw_result in rows.scalars().all():
            result = dict(raw_result or {})
            nested_result = result.get("result")
            payload = nested_result if isinstance(nested_result, dict) else result
            metadata = dict(payload.get("metadata") or {})
            if any(
                isinstance(item, dict) and item.get("action_ref") == action_ref
                for item in metadata.get("action_catalog") or []
            ):
                catalogued = True
                break
        if not catalogued:
            return {"status": "failed", "error": "production_action_not_catalogued_in_response"}
        try:
            result = await execute_production_action(
                db,
                scope=ProductionScope(response.tenant_id, response.workspace_id, response.user_id),
                response_id=response.id,
                user=user,
                action_ref=action_ref,
                query=_response_query(dict(response.request_payload or {})),
                trace_id=response.id,
            )
            await db.commit()
            return result
        except ValueError as exc:
            await db.rollback()
            outcome_unknown = bool(getattr(exc, "outcome_unknown", False))
            return {
                "status": "incomplete" if outcome_unknown else "failed",
                "error": str(exc),
                "requires_reconciliation": outcome_unknown,
            }


def _response_query(payload: dict[str, Any]) -> str:
    raw_input = payload.get("input")
    if isinstance(raw_input, str):
        return raw_input
    if not isinstance(raw_input, list):
        return ""
    parts: list[str] = []
    for item in raw_input:
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(
                str(block.get("text") or "")
                for block in content
                if isinstance(block, dict) and block.get("type") in {"input_text", "text"}
            )
    return "\n".join(part for part in parts if part).strip()
