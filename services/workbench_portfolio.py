"""企业工作台的 Project 工作组合投影。

该模块把当前员工可见的 Project、Responses、Goal、审批、自动化和预警聚合为
可解释的工作组合健康状态。它只处理已经按作用域读取的 PostgreSQL 事实，不触发
模型、工具或后台任务。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

ACTIVE_RESPONSE_STATUSES = {"queued", "in_progress", "requires_action"}
ACTIVE_GOAL_STATUSES = {"queued", "in_progress", "requires_action", "paused"}
FAILED_RESPONSE_STATUSES = {"failed", "incomplete"}
DEFAULT_CONVERSATION_TITLES = {"new conversation", "新对话", "新会话"}
UNASSIGNED_KEY = "__unassigned__"


def _value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(parsed, datetime):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _timestamp(value: Any) -> int:
    parsed = _as_utc(value)
    return int(parsed.timestamp()) if parsed else 0


def _bounded_text(value: Any, *, limit: int = 100) -> str:
    if isinstance(value, list):
        value = " ".join(
            (
                str(item.get("text") or item.get("content") or "")
                if isinstance(item, dict)
                else str(item)
            )
            for item in value
        )
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _conversation_title(session: Any, response: Any) -> str:
    for candidate in (_value(session, "display_title"), _value(session, "title")):
        title = _bounded_text(candidate)
        if title and title.casefold() not in DEFAULT_CONVERSATION_TITLES:
            return title
    request = _value(response, "request_payload", {}) or {}
    return _bounded_text(request.get("input") if isinstance(request, dict) else "") or "AI 工作"


def _conversation_route(conversation_id: Any) -> str:
    return f"/chat?conversation={conversation_id}"


def _automation_route(row: Any, *, kind: str) -> str:
    if kind == "alert":
        return "/alerts"
    return "/reports" if _value(row, "task_type") == "enterprise_report" else "/tasks"


def _new_bucket(project: Any | None) -> dict[str, Any]:
    project_id = str(_value(project, "id")) if project is not None else None
    return {
        "project_id": project_id,
        "name": str(_value(project, "name") or "未归入 Project"),
        "description": str(
            _value(project, "description")
            or (
                "这些工作尚未绑定 Project，无法复用稳定业务指令、Project 记忆和数据授权。"
                if project is None
                else ""
            )
        ),
        "instructions_ready": bool(str(_value(project, "instructions") or "").strip()),
        "data_source_count": len(_value(project, "data_source_ids", []) or []),
        "active_responses": 0,
        "active_goals": 0,
        "paused_goals": 0,
        "pending_approvals": 0,
        "failed_responses_7d": 0,
        "unacknowledged_alerts": 0,
        "critical_alerts": 0,
        "active_automations": 0,
        "delivered_turns_7d": 0,
        "active_work_keys": set(),
        "actions": [],
        "last_activity_at": _as_utc(_value(project, "updated_at")),
    }


def _touch(bucket: dict[str, Any], value: Any) -> None:
    timestamp = _as_utc(value)
    if timestamp and (bucket["last_activity_at"] is None or timestamp > bucket["last_activity_at"]):
        bucket["last_activity_at"] = timestamp


def _add_action(
    bucket: dict[str, Any],
    *,
    weight: int,
    action_type: str,
    label: str,
    title: str,
    description: str,
    route: str,
    created_at: Any = None,
) -> None:
    bucket["actions"].append(
        {
            "_weight": weight,
            "type": action_type,
            "label": label,
            "title": _bounded_text(title, limit=120),
            "description": _bounded_text(description, limit=180),
            "route": route,
            "created_at": _iso(_as_utc(created_at)),
        }
    )


def _project_key(project_id: Any, known_project_ids: set[str]) -> str:
    candidate = str(project_id) if project_id else ""
    return candidate if candidate in known_project_ids else UNASSIGNED_KEY


def _status(bucket: dict[str, Any]) -> tuple[str, str]:
    if bucket["critical_alerts"]:
        return "critical", f"有 {bucket['critical_alerts']} 个关键业务预警未确认"
    if bucket["failed_responses_7d"]:
        return "critical", f"近 7 天有 {bucket['failed_responses_7d']} 次 AI 工作未完成"
    if bucket["pending_approvals"]:
        return "attention", f"有 {bucket['pending_approvals']} 个副作用操作等待审批"
    if bucket["unacknowledged_alerts"]:
        return "attention", f"有 {bucket['unacknowledged_alerts']} 个业务预警等待确认"
    if bucket["paused_goals"]:
        return "attention", f"有 {bucket['paused_goals']} 个 Goal 处于暂停状态"
    if bucket["project_id"] is None:
        return "attention", "当前工作尚未归入稳定的 Project 上下文"
    if bucket["active_work_keys"] or bucket["active_automations"]:
        return "active", "工作和自动化正在按持久状态推进"
    if bucket["instructions_ready"]:
        return "ready", "业务指令已就绪，可以开始新的 AI 工作"
    return "foundation", "需要先补充业务背景、术语和输出约束"


def build_workbench_portfolio(
    *,
    projects: list[Any],
    sessions: list[Any],
    responses: list[Any],
    goals: list[Any],
    pending_approvals: list[Any],
    tasks: list[Any],
    alerts: list[Any],
    alert_events: list[Any],
    now: datetime | None = None,
    window_days: int = 7,
    response_candidate_limit: int | None = None,
    response_candidates_truncated: bool = False,
) -> dict[str, Any]:
    """按 Project 聚合当前工作健康状态，并为每项工作生成唯一下一步。"""

    current = _as_utc(now) or datetime.now(UTC)
    period_days = max(1, min(window_days, 30))
    window_start = current - timedelta(days=period_days)
    known_project_ids = {str(_value(row, "id")) for row in projects}
    buckets = {str(_value(row, "id")): _new_bucket(row) for row in projects}
    buckets[UNASSIGNED_KEY] = _new_bucket(None)
    session_by_id = {str(_value(row, "id")): row for row in sessions}
    goal_by_id = {str(_value(row, "id")): row for row in goals}
    response_by_id = {str(_value(row, "id")): row for row in responses}
    response_project: dict[str, str] = {}

    for response in responses:
        response_id = str(_value(response, "id"))
        conversation_id = str(_value(response, "conversation_id") or "")
        session = session_by_id.get(conversation_id)
        goal = goal_by_id.get(str(_value(response, "goal_id") or ""))
        project_id = _value(goal, "project_id") or _value(session, "project_id")
        key = _project_key(project_id, known_project_ids)
        response_project[response_id] = key
        bucket = buckets[key]
        status = str(_value(response, "status") or "")
        updated_at = _as_utc(_value(response, "updated_at"))
        completed_at = _as_utc(_value(response, "completed_at"))
        _touch(bucket, updated_at)
        if status in ACTIVE_RESPONSE_STATUSES:
            bucket["active_responses"] += 1
            bucket["active_work_keys"].add(f"conversation:{conversation_id}")
            label = "处理所需操作" if status == "requires_action" else "查看执行进度"
            _add_action(
                bucket,
                weight=820 if status == "requires_action" else 700,
                action_type="response",
                label=label,
                title=_conversation_title(session, response),
                description=(
                    "Response 正在等待人工操作。"
                    if status == "requires_action"
                    else f"Response 当前状态为 {status}，可查看持久事件与输出。"
                ),
                route=_conversation_route(conversation_id),
                created_at=updated_at,
            )
        if status in FAILED_RESPONSE_STATUSES and updated_at and updated_at >= window_start:
            bucket["failed_responses_7d"] += 1
            _add_action(
                bucket,
                weight=900,
                action_type="response",
                label="检查并重试",
                title=_conversation_title(session, response),
                description=str(
                    _value(response, "error_message") or "执行未完整结束，请查看事件后安全重试。"
                ),
                route=_conversation_route(conversation_id),
                created_at=updated_at,
            )
        if status == "completed" and completed_at and completed_at >= window_start:
            bucket["delivered_turns_7d"] += 1
            _add_action(
                bucket,
                weight=200,
                action_type="continue",
                label="继续工作",
                title=_conversation_title(session, response),
                description="最近一轮已完成，可沿同一持久会话继续下一步。",
                route=_conversation_route(conversation_id),
                created_at=completed_at,
            )

    for goal in goals:
        key = _project_key(_value(goal, "project_id"), known_project_ids)
        bucket = buckets[key]
        status = str(_value(goal, "status") or "")
        conversation_id = _value(goal, "conversation_id")
        updated_at = _value(goal, "updated_at")
        _touch(bucket, updated_at)
        if status not in ACTIVE_GOAL_STATUSES:
            continue
        bucket["active_goals"] += 1
        work_key = (
            f"conversation:{conversation_id}" if conversation_id else f"goal:{_value(goal, 'id')}"
        )
        bucket["active_work_keys"].add(work_key)
        if status == "paused":
            bucket["paused_goals"] += 1
        route = _conversation_route(conversation_id) if conversation_id else "/work?tab=goals"
        _add_action(
            bucket,
            weight=760 if status in {"requires_action", "paused"} else 650,
            action_type="goal",
            label=(
                "处理所需操作"
                if status == "requires_action"
                else "恢复 Goal" if status == "paused" else "查看 Goal"
            ),
            title=str(_value(goal, "objective") or "长期 Goal"),
            description=f"Goal 当前状态为 {status}，检查点 {_value(goal, 'current_step', 0)}。",
            route=route,
            created_at=updated_at,
        )

    for source in pending_approvals:
        if isinstance(source, tuple):
            approval = source[0]
            approval_conversation_id = source[1] if len(source) > 1 else None
            approval_project_id = source[2] if len(source) > 2 else None
        else:
            approval, approval_conversation_id, approval_project_id = source, None, None
        response_id = str(_value(approval, "response_id") or "")
        response = response_by_id.get(response_id)
        if approval_conversation_id is None and response is not None:
            approval_conversation_id = _value(response, "conversation_id")
        approval_key = response_project.get(response_id)
        if approval_key is None:
            session = session_by_id.get(str(approval_conversation_id or ""))
            source_project_id = approval_project_id or _value(session, "project_id")
            approval_key = _project_key(source_project_id, known_project_ids)
        bucket = buckets[approval_key]
        bucket["pending_approvals"] += 1
        _touch(bucket, _value(approval, "created_at"))
        _add_action(
            bucket,
            weight=850,
            action_type="approval",
            label="处理审批",
            title=f"待审批：{_value(approval, 'tool_name') or '副作用操作'}",
            description=f"{_value(approval, 'side_effect_level') or 'write'} 操作等待人工确认。",
            route=_conversation_route(approval_conversation_id),
            created_at=_value(approval, "created_at"),
        )

    alert_by_id = {str(_value(row, "id")): row for row in alerts}
    for event in alert_events:
        rule = alert_by_id.get(str(_value(event, "rule_id") or ""))
        key = _project_key(_value(rule, "project_id"), known_project_ids)
        bucket = buckets[key]
        bucket["unacknowledged_alerts"] += 1
        severity = str(_value(event, "severity") or "warning")
        if severity == "critical":
            bucket["critical_alerts"] += 1
        _touch(bucket, _value(event, "created_at"))
        _add_action(
            bucket,
            weight=1000 if severity == "critical" else 940,
            action_type="alert",
            label="确认预警",
            title=str(_value(event, "summary") or _value(rule, "name") or "业务指标预警"),
            description="查看触发证据、当前值和规则口径后确认处置。",
            route="/alerts",
            created_at=_value(event, "created_at"),
        )

    for row, kind in [*((row, "task") for row in tasks), *((row, "alert") for row in alerts)]:
        if str(_value(row, "status") or "") != "active":
            continue
        key = _project_key(_value(row, "project_id"), known_project_ids)
        bucket = buckets[key]
        bucket["active_automations"] += 1
        next_run_at = _value(row, "next_run_at")
        _touch(bucket, _value(row, "updated_at") or _value(row, "last_run_at"))
        title = str(_value(row, "title") or _value(row, "name") or "企业自动化")
        _add_action(
            bucket,
            weight=500,
            action_type="automation",
            label="查看自动化",
            title=title,
            description=(
                f"下一计划时间：{_iso(_as_utc(next_run_at))}"
                if next_run_at
                else "自动化已启用，等待调度生成下一次运行时间。"
            ),
            route=_automation_route(row, kind=kind),
            created_at=next_run_at,
        )

    items: list[dict[str, Any]] = []
    for key, bucket in buckets.items():
        has_work = bool(
            bucket["active_work_keys"]
            or bucket["pending_approvals"]
            or bucket["failed_responses_7d"]
            or bucket["unacknowledged_alerts"]
            or bucket["active_automations"]
            or bucket["delivered_turns_7d"]
        )
        if key == UNASSIGNED_KEY and not has_work:
            continue
        if key == UNASSIGNED_KEY:
            _add_action(
                bucket,
                weight=250,
                action_type="organize",
                label="建立 Project",
                title="将持续工作归入 Project",
                description="沉淀业务指令、记忆范围和企业数据授权，避免每轮重新解释上下文。",
                route="/work?tab=projects",
            )
        elif not bucket["instructions_ready"]:
            _add_action(
                bucket,
                weight=300,
                action_type="setup",
                label="完善上下文",
                title="补充 Project 业务指令",
                description="写明业务背景、术语、输出规范和决策约束。",
                route="/work?tab=projects",
            )
        else:
            _add_action(
                bucket,
                weight=100,
                action_type="start",
                label="开始新工作",
                title="在当前 Project 中发起 AI 工作",
                description="聊天页会继承该 Project 的指令、记忆和数据授权。",
                route="/chat",
            )
        actions = sorted(
            bucket["actions"],
            key=lambda item: (item["_weight"], str(item.get("created_at") or "")),
            reverse=True,
        )
        next_action = dict(actions[0])
        next_action.pop("_weight", None)
        status, status_reason = _status(bucket)
        items.append(
            {
                "project_id": bucket["project_id"],
                "name": bucket["name"],
                "description": bucket["description"],
                "status": status,
                "status_reason": status_reason,
                "instructions_ready": bucket["instructions_ready"],
                "data_source_count": bucket["data_source_count"],
                "active_work": len(bucket["active_work_keys"]),
                "active_responses": bucket["active_responses"],
                "active_goals": bucket["active_goals"],
                "pending_approvals": bucket["pending_approvals"],
                "failed_responses_7d": bucket["failed_responses_7d"],
                "unacknowledged_alerts": bucket["unacknowledged_alerts"],
                "active_automations": bucket["active_automations"],
                "delivered_turns_7d": bucket["delivered_turns_7d"],
                "last_activity_at": _iso(bucket["last_activity_at"]),
                "next_action": next_action,
            }
        )

    status_order = {"critical": 0, "attention": 1, "active": 2, "foundation": 3, "ready": 4}
    items.sort(
        key=lambda item: (
            status_order[item["status"]],
            -_timestamp(item["last_activity_at"]),
            item["name"],
        )
    )
    summary = {
        "projects": len(projects),
        "critical_projects": sum(item["status"] == "critical" for item in items),
        "attention_projects": sum(item["status"] == "attention" for item in items),
        "active_projects": sum(item["status"] == "active" for item in items),
        "active_work": sum(item["active_work"] for item in items),
        "pending_approvals": sum(item["pending_approvals"] for item in items),
        "unacknowledged_alerts": sum(item["unacknowledged_alerts"] for item in items),
        "delivered_turns_7d": sum(item["delivered_turns_7d"] for item in items),
        "unassigned_work": next(
            (item["active_work"] for item in items if item["project_id"] is None), 0
        ),
    }
    return {
        "window_days": period_days,
        "window_start": window_start.isoformat(),
        "response_candidate_limit": response_candidate_limit,
        "response_candidates_truncated": response_candidates_truncated,
        "summary": summary,
        "items": items,
    }
