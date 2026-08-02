from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.config.constants import DEFAULT_TIMEZONE
from infra.storage.models import ResponseApproval, ResponseRecord
from kernel.agent_loop.contracts import (
    ExecutionPlan,
    ExecutionStep,
    IntentPlan,
    PlanningDecision,
    SideEffect,
    ToolSpec,
)
from kernel.agent_loop.write_intent import is_affirmative_follow_up
from services.calendar_intent import has_calendar_write_intent, parse_calendar_create_intent

_CONTEXTUAL_CALENDAR_HINT = re.compile(
    r"日历|日程|会议|评审|复盘|开发|学习|写作|专注|提醒|安排|计划|准备|参加|开会|"
    r"今天|明天|后天|(?:\d{1,2}|[一二两三四五六七八九十]{1,3})(?:点|[:：])"
)

_CALENDAR_CAPABILITIES = {
    "list_calendar_events",
    "get_calendar_event_history",
    "create_calendar_event",
    "update_calendar_event",
    "cancel_calendar_event",
}
_FAILED_STATUSES = {"error", "failed", "incomplete", "rejected", "timeout"}


def _coerce_schema_value(value: Any, schema: dict[str, Any]) -> Any:
    value_type = schema.get("type")
    allowed_types = set(value_type) if isinstance(value_type, list) else {value_type}
    if value is None and "null" in allowed_types:
        return None
    if "boolean" in allowed_types and isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no", ""}:
            return False
    if "integer" in allowed_types and isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return value
    if "number" in allowed_types and isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return value
    if "array" in allowed_types:
        candidate = value
        if isinstance(value, str):
            try:
                candidate = json.loads(value)
            except (TypeError, ValueError):
                return value
        if isinstance(candidate, list):
            item_schema = dict(schema.get("items") or {})
            return [_coerce_schema_value(item, item_schema) for item in candidate]
    if "object" in allowed_types and isinstance(value, str):
        try:
            candidate = json.loads(value)
        except (TypeError, ValueError):
            return value
        if isinstance(candidate, dict):
            return candidate
    if "string" in allowed_types and not isinstance(value, str):
        return str(value)
    return value


def _normalize_tool_call(
    *,
    call_id: str,
    name: str,
    arguments: dict[str, Any],
    spec: ToolSpec,
) -> dict[str, Any]:
    properties = dict(spec.parameters.get("properties") or {})
    normalized_arguments = {
        property_name: _coerce_schema_value(arguments[property_name], dict(schema or {}))
        for property_name, schema in properties.items()
        if property_name in arguments
    }
    return {
        "id": call_id,
        "call_id": call_id,
        "name": name,
        "type": "function",
        "arguments": normalized_arguments,
        "function": {"name": name, "arguments": normalized_arguments},
    }


def deterministic_calendar_arguments(
    *,
    query: str,
    response: ResponseRecord,
    extension: dict[str, Any],
    tool_specs: list[ToolSpec],
    prior_user_queries: list[str] | None = None,
) -> dict[str, Any] | None:
    spec = next((item for item in tool_specs if item.name == "create_calendar_event"), None)
    if spec is None or spec.side_effect == SideEffect.READ:
        return None
    anchor = getattr(response, "created_at", None)
    if isinstance(anchor, datetime) and anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    parse_kwargs = {
        "timezone_name": str(extension.get("timezone") or DEFAULT_TIMEZONE),
        "now": anchor if isinstance(anchor, datetime) else None,
    }
    current = parse_calendar_create_intent(
        query,
        **parse_kwargs,
    )
    if current and str(current.get("title") or "").strip() not in {"", "日程"}:
        return current
    if not has_calendar_write_intent(query):
        return current

    # 用户常分两轮给出事项与时间。只尝试最近的用户原话，并要求当前回合本身包含
    # 明确写入意图，避免从较早对话推断新的副作用操作。
    for prior_query in reversed(prior_user_queries or []):
        prior_query = str(prior_query or "").strip()
        if (
            not prior_query
            or "?" in prior_query
            or "？" in prior_query
            or not _CONTEXTUAL_CALENDAR_HINT.search(prior_query)
        ):
            continue
        contextual_query = query
        if not re.search(r"上午|下午|晚上|中午|凌晨", query):
            period_matches = re.findall(r"上午|下午|晚上|中午|凌晨", prior_query)
            if period_matches:
                contextual_query = re.sub(
                    r"(?P<time>(?:\d{1,2}|[零〇一二两三四五六七八九十]{1,3})(?:点|[:：]))",
                    period_matches[-1] + r"\g<time>",
                    query,
                    count=1,
                )
        contextual = parse_calendar_create_intent(
            f"{prior_query}\n{contextual_query}",
            **parse_kwargs,
        )
        if contextual and str(contextual.get("title") or "").strip() not in {"", "日程"}:
            return contextual
    return current


async def existing_deterministic_approval(
    db: AsyncSession,
    *,
    response: ResponseRecord,
    tool_specs: list[ToolSpec],
) -> ResponseApproval | None:
    if not any(spec.name == "create_calendar_event" for spec in tool_specs):
        return None
    return await db.scalar(
        select(ResponseApproval)
        .where(
            ResponseApproval.response_id == response.id,
            ResponseApproval.tool_name == "create_calendar_event",
            ResponseApproval.call_id.like("call_deterministic_%"),
        )
        .order_by(ResponseApproval.created_at.desc())
    )


def supplement_deterministic_calendar_decision(
    decision: PlanningDecision,
    *,
    spec: ToolSpec,
) -> PlanningDecision:
    risk_order = {SideEffect.READ: 0, SideEffect.WRITE: 1, SideEffect.DESTRUCTIVE: 2}
    capabilities = tuple(
        dict.fromkeys(
            (
                *(
                    capability
                    for capability in decision.intent.capabilities
                    if capability not in _CALENDAR_CAPABILITIES
                ),
                spec.name,
            )
        )
    )
    intent = IntentPlan(
        goal=decision.intent.goal,
        task_type=decision.intent.task_type,
        capabilities=capabilities,
        ambiguity=None,
        risk=max(decision.intent.risk, spec.side_effect, key=risk_order.__getitem__),
        execution_profile=decision.intent.execution_profile,
        execution_mode=decision.intent.execution_mode,
        expected_outputs=decision.intent.expected_outputs,
        clarification_question=None,
    )
    plan = decision.execution_plan
    retained_steps = tuple(
        step
        for step in plan.steps
        if step.capability not in _CALENDAR_CAPABILITIES or step.capability == spec.name
    )
    if any(step.capability == spec.name for step in retained_steps):
        return PlanningDecision(
            intent=intent,
            execution_plan=ExecutionPlan(
                goal=plan.goal,
                complexity=plan.complexity,
                steps=retained_steps,
                success_criteria=plan.success_criteria,
                replan_limit=plan.replan_limit,
            ),
        )
    known_ids = {step.id for step in retained_steps}
    step_id = "step_calendar_create"
    suffix = 2
    while step_id in known_ids:
        step_id = f"step_calendar_create_{suffix}"
        suffix += 1
    supplemented_plan = ExecutionPlan(
        goal=plan.goal,
        complexity=plan.complexity,
        steps=(
            *retained_steps,
            ExecutionStep(
                id=step_id,
                objective="创建用户明确指定的个人日历日程",
                capability=spec.name,
                depends_on=(),
                success_criteria="日程经用户审批后写入个人日历",
            ),
        ),
        success_criteria=plan.success_criteria,
        replan_limit=plan.replan_limit,
    )
    return PlanningDecision(intent=intent, execution_plan=supplemented_plan)


def _calendar_result_succeeded(result: dict[str, Any]) -> bool:
    status = str(result.get("status") or "").lower()
    nested = result.get("result")
    nested_result = nested if isinstance(nested, dict) else {}
    nested_status = str(nested_result.get("status") or "").lower()
    if status in _FAILED_STATUSES or nested_status in _FAILED_STATUSES:
        return False
    return status in {"completed", "success", "ok"} or nested_status in {
        "completed",
        "success",
        "ok",
    }


def _calendar_local_time(value: Any, timezone_name: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def _calendar_time_label(arguments: dict[str, Any]) -> str:
    timezone_name = str(arguments.get("timezone") or DEFAULT_TIMEZONE)
    start = _calendar_local_time(arguments.get("start_at"), timezone_name)
    end = _calendar_local_time(arguments.get("end_at"), timezone_name)
    if start is None:
        return "时间已按审批参数写入"
    date_label = f"{start.year}年{start.month}月{start.day}日"
    if bool(arguments.get("all_day")):
        return f"{date_label}（全天）"
    if end is None:
        return f"{date_label} {start:%H:%M}"
    if start.date() == end.date():
        return f"{date_label} {start:%H:%M}–{end:%H:%M}"
    end_label = f"{end.year}年{end.month}月{end.day}日 {end:%H:%M}"
    return f"{date_label} {start:%H:%M}–{end_label}"


def deterministic_calendar_completion(
    *,
    approval: ResponseApproval | None,
    restored_tools: list[tuple[str, dict[str, Any]]],
) -> str | None:
    if (
        approval is None
        or approval.status != "approved"
        or approval.tool_name != "create_calendar_event"
        or not str(approval.call_id or "").startswith("call_deterministic_")
    ):
        return None
    result = next(
        (
            item
            for tool_name, item in reversed(restored_tools)
            if tool_name == "create_calendar_event" and _calendar_result_succeeded(item)
        ),
        None,
    )
    if result is None:
        return None
    nested = result.get("result")
    nested_result = nested if isinstance(nested, dict) else {}
    event = nested_result.get("event")
    event_payload = event if isinstance(event, dict) else {}
    arguments = dict(approval.arguments or result.get("parameters") or {})
    title = str(event_payload.get("title") or arguments.get("title") or "未命名日程").strip()
    timezone_name = str(
        arguments.get("timezone") or event_payload.get("timezone") or DEFAULT_TIMEZONE
    )
    reminders = [
        int(value)
        for value in arguments.get("reminder_minutes") or []
        if isinstance(value, int) and value >= 0
    ]
    lines = [
        "已记录 ✅",
        "",
        f"- 日程：{title}",
        f"- 时间：{_calendar_time_label(arguments)}（{timezone_name}）",
    ]
    if reminders:
        lines.append("- 提醒：" + "、".join(f"提前 {value} 分钟" for value in reminders))
    lines.extend(("- 状态：已写入个人日历", "", "[查看我的日历](/calendar)"))
    return "\n".join(lines)


def deterministic_write_call(
    *,
    query: str,
    response: ResponseRecord,
    extension: dict[str, Any],
    tool_specs: list[ToolSpec],
    pending_action: dict[str, Any] | None,
    calendar_arguments: dict[str, Any] | None = None,
    existing_approval: ResponseApproval | None = None,
) -> tuple[dict[str, Any], ToolSpec] | None:
    spec_by_name = {spec.name: spec for spec in tool_specs}
    name = ""
    arguments: dict[str, Any] | None = None
    if pending_action and is_affirmative_follow_up(query):
        name = str(pending_action.get("name") or "")
        arguments = dict(pending_action.get("arguments") or {})
    else:
        name = "create_calendar_event"
        if name in spec_by_name:
            arguments = calendar_arguments or deterministic_calendar_arguments(
                query=query,
                response=response,
                extension=extension,
                tool_specs=tool_specs,
            )
    spec = spec_by_name.get(name)
    if spec is None or spec.side_effect == SideEffect.READ or not arguments:
        return None
    if existing_approval is not None and existing_approval.tool_name == name:
        call_id = existing_approval.call_id
        arguments = dict(existing_approval.arguments or arguments)
    else:
        fingerprint = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
        call_id = (
            "call_deterministic_"
            + hashlib.sha256(f"{response.id}:{name}:{fingerprint}".encode()).hexdigest()[:24]
        )
    return (
        _normalize_tool_call(
            call_id=call_id,
            name=name,
            arguments=arguments,
            spec=spec,
        ),
        spec,
    )
