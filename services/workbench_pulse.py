"""企业工作台的确定性今日脉搏投影。

该模块只基于已持久化事实计算优先级、逾期和当日日程，不触发模型、工具或后台任务。
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

ACTIVE_GOAL_STATUSES = {"queued", "in_progress", "requires_action", "paused"}
STALE_GOAL_HOURS = 72

_SEVERITY_SCORE = {
    "critical": 100,
    "error": 90,
    "warning": 60,
    "info": 25,
    "success": 10,
}
_TYPE_SCORE = {
    "alert": 30,
    "approval": 30,
    "automation": 20,
    "response": 20,
    "goal": 10,
    "knowledge": 5,
    "notification": 5,
}


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


def _duration_label(delta: timedelta) -> str:
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 3600:
        return f"{max(1, seconds // 60)} 分钟"
    hours = seconds // 3600
    if hours < 48:
        return f"{hours} 小时"
    return f"{hours // 24} 天"


def _priority(score: int) -> str:
    if score >= 120:
        return "p0"
    if score >= 90:
        return "p1"
    if score >= 60:
        return "p2"
    return "p3"


def _default_reason(item: dict[str, Any], *, age: timedelta) -> str:
    item_type = str(item.get("type") or "")
    if item_type == "approval":
        return f"审批已等待 {_duration_label(age)}"
    if item_type == "alert":
        return "关键业务预警尚未确认"
    if item_type == "response":
        return "Responses 执行失败或未完整结束"
    if item_type == "knowledge":
        return "知识治理事项可能影响回答可信度"
    if item_type == "goal":
        return "长期目标缺少近期进展"
    if item_type == "automation":
        return "自动化运行时间已到"
    return "存在需要查看的企业工作状态"


def rank_workbench_actions(
    items: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """按风险、事项类型、等待时长和逾期程度生成可解释优先级。"""

    current = _as_utc(now) or datetime.now(UTC)
    ranked: list[dict[str, Any]] = []
    for source in items:
        item = dict(source)
        created_at = _as_utc(item.get("created_at"))
        due_at = _as_utc(item.get("due_at"))
        age = current - created_at if created_at and current >= created_at else timedelta(0)
        score = _SEVERITY_SCORE.get(str(item.get("severity") or "info"), 25)
        score += _TYPE_SCORE.get(str(item.get("type") or ""), 0)
        score += min(20, max(0, int(age.total_seconds() // 7200)))
        if item.get("type") == "approval" and age >= timedelta(hours=4):
            score += 10
        if due_at and due_at < current:
            overdue = current - due_at
            score += 35 if overdue >= timedelta(hours=2) else 20
            item["overdue"] = True
        else:
            item["overdue"] = False
        item["age_minutes"] = max(0, int(age.total_seconds() // 60))
        item["priority_score"] = score
        item["priority"] = _priority(score)
        item["priority_reason"] = str(item.get("priority_reason") or _default_reason(item, age=age))
        ranked.append(item)

    return sorted(
        ranked,
        key=lambda item: (
            -int(item["priority_score"]),
            str(item.get("due_at") or "9999"),
            str(item.get("created_at") or ""),
        ),
    )


def _automation_focus_item(row: Any, *, kind: str, now: datetime) -> dict[str, Any] | None:
    due_at = _as_utc(_value(row, "next_run_at"))
    if due_at is None or due_at >= now or _value(row, "status") != "active":
        return None
    overdue = now - due_at
    is_critical = overdue >= timedelta(hours=2)
    title = str(_value(row, "title") or _value(row, "name") or "企业自动化")
    is_report = _value(row, "task_type") == "enterprise_report"
    route = "/alerts" if kind == "alert" else "/reports" if is_report else "/tasks"
    return {
        "id": str(_value(row, "id")),
        "type": "automation",
        "severity": "critical" if is_critical else "warning",
        "title": f"自动化逾期：{title}",
        "description": f"计划运行时间已过去 {_duration_label(overdue)}，请检查 Worker、依赖或任务状态。",
        "route": route,
        "resource_id": str(_value(row, "id")),
        "created_at": _iso(due_at),
        "due_at": _iso(due_at),
        "priority_reason": f"自动化已逾期 {_duration_label(overdue)}",
    }


def _stale_goal_item(row: Any, *, now: datetime) -> dict[str, Any] | None:
    updated_at = _as_utc(_value(row, "updated_at"))
    if (
        _value(row, "status") not in ACTIVE_GOAL_STATUSES
        or updated_at is None
        or now - updated_at < timedelta(hours=STALE_GOAL_HOURS)
    ):
        return None
    stale_for = now - updated_at
    objective = " ".join(str(_value(row, "objective") or "长期 Goal").split())
    if len(objective) > 90:
        objective = f"{objective[:89]}…"
    return {
        "id": str(_value(row, "id")),
        "type": "goal",
        "severity": "warning",
        "title": f"Goal 待推进：{objective}",
        "description": f"已 {_duration_label(stale_for)} 没有新检查点或状态更新。",
        "route": "/work?tab=goals",
        "resource_id": str(_value(row, "id")),
        "created_at": _iso(updated_at),
        "priority_reason": f"Goal 已 {_duration_label(stale_for)} 未推进",
    }


def _calendar_timeline_item(item: dict[str, Any], *, now: datetime) -> dict[str, Any] | None:
    start_at = _as_utc(item.get("start_at"))
    end_at = _as_utc(item.get("end_at"))
    if start_at is None or end_at is None:
        return None
    if now < start_at:
        status = "upcoming"
    elif now < end_at:
        status = "in_progress"
    else:
        status = "completed"
    return {
        "id": str(item.get("occurrence_id") or item.get("id")),
        "type": "calendar",
        "title": str(item.get("title") or "日程"),
        "description": str(item.get("location") or item.get("description") or "个人日历安排"),
        "status": status,
        "route": "/calendar",
        "start_at": _iso(start_at),
        "end_at": _iso(end_at),
        "event_type": str(item.get("event_type") or "event"),
        "sort_at": start_at,
    }


def _automation_timeline_item(row: Any, *, kind: str, now: datetime) -> dict[str, Any] | None:
    next_run_at = _as_utc(_value(row, "next_run_at"))
    if next_run_at is None or _value(row, "status") != "active":
        return None
    title = str(_value(row, "title") or _value(row, "name") or "企业自动化")
    is_report = _value(row, "task_type") == "enterprise_report"
    route = "/alerts" if kind == "alert" else "/reports" if is_report else "/tasks"
    return {
        "id": str(_value(row, "id")),
        "type": kind,
        "title": title,
        "description": "下一次指标检查" if kind == "alert" else "下一次自动运行",
        "status": "overdue" if next_run_at < now else "scheduled",
        "route": route,
        "start_at": _iso(next_run_at),
        "end_at": None,
        "sort_at": next_run_at,
    }


def build_workbench_operating_pulse(
    *,
    attention_items: list[dict[str, Any]],
    tasks: list[Any],
    alerts: list[Any],
    goals: list[Any],
    calendar_events: list[dict[str, Any]],
    timezone_name: str,
    now: datetime | None = None,
    focus_limit: int = 8,
    timeline_limit: int = 12,
) -> dict[str, Any]:
    """生成员工今天先做什么、接下来发生什么的工作台投影。"""

    zone = ZoneInfo(timezone_name)
    current = _as_utc(now) or datetime.now(UTC)
    local_now = current.astimezone(zone)
    day_start_local = datetime.combine(local_now.date(), time.min, tzinfo=zone)
    day_end_local = day_start_local + timedelta(days=1)
    day_start = day_start_local.astimezone(UTC)
    day_end = day_end_local.astimezone(UTC)

    automation_rows = [(row, "task") for row in tasks] + [(row, "alert") for row in alerts]
    overdue_items = [
        item
        for row, kind in automation_rows
        if (item := _automation_focus_item(row, kind=kind, now=current)) is not None
    ]
    stale_goal_items = [
        item for row in goals if (item := _stale_goal_item(row, now=current)) is not None
    ]
    candidates = [*attention_items, *overdue_items, *stale_goal_items[:3]]
    actionable_resources = {
        str(item.get("resource_id"))
        for item in candidates
        if item.get("type") != "notification" and item.get("resource_id")
    }
    candidates = [
        item
        for item in candidates
        if not (
            item.get("type") == "notification"
            and item.get("resource_id")
            and str(item.get("resource_id")) in actionable_resources
        )
    ]
    ranked_focus_items = rank_workbench_actions(candidates, now=current)
    focus_items = ranked_focus_items[: max(1, min(focus_limit, 20))]

    timeline: list[dict[str, Any]] = []
    for event in calendar_events:
        item = _calendar_timeline_item(event, now=current)
        event_start = _as_utc(item.get("start_at")) if item else None
        event_end = _as_utc(item.get("end_at")) if item else None
        if item and event_start and event_end and event_end > day_start and event_start < day_end:
            item["sort_at"] = max(event_start, day_start)
            timeline.append(item)
    for row, kind in automation_rows:
        item = _automation_timeline_item(row, kind=kind, now=current)
        if item and day_start <= item["sort_at"] < day_end:
            timeline.append(item)
    timeline.sort(key=lambda item: item["sort_at"])
    calendar_count = sum(1 for item in timeline if item["type"] == "calendar")
    due_automation_count = sum(1 for item in timeline if item["type"] in {"task", "alert"})
    timeline = timeline[: max(1, min(timeline_limit, 30))]
    for item in timeline:
        item.pop("sort_at", None)

    overdue_automation_count = len(overdue_items)
    urgent_count = sum(1 for item in ranked_focus_items if item["priority"] in {"p0", "p1"})
    p0_count = sum(1 for item in ranked_focus_items if item["priority"] == "p0")
    focus_minutes = 0
    meeting_minutes = 0
    for event in calendar_events:
        start_at = _as_utc(event.get("start_at"))
        end_at = _as_utc(event.get("end_at"))
        if start_at is None or end_at is None or end_at <= day_start or start_at >= day_end:
            continue
        visible_start = max(start_at, day_start)
        visible_end = min(end_at, day_end)
        duration_minutes = max(0, int((visible_end - visible_start).total_seconds() // 60))
        if event.get("event_type") == "focus":
            focus_minutes += duration_minutes
        if event.get("event_type") == "meeting":
            meeting_minutes += duration_minutes

    if p0_count:
        status = "critical"
        headline = f"有 {p0_count} 项高风险工作需要立即处理"
    elif urgent_count:
        status = "attention"
        headline = f"有 {urgent_count} 项优先工作等待处理"
    elif focus_items:
        status = "attention"
        headline = f"今日有 {len(focus_items)} 项工作需要跟进"
    elif timeline:
        status = "clear"
        headline = f"当前无阻塞，今日有 {len(timeline)} 个计划节点"
    else:
        status = "clear"
        headline = "当前无高优先级阻塞，可按计划推进"

    return {
        "timezone": timezone_name,
        "local_date": local_now.date().isoformat(),
        "day_start": day_start.isoformat(),
        "day_end": day_end.isoformat(),
        "status": status,
        "headline": headline,
        "summary": {
            "urgent_items": urgent_count,
            "calendar_events": calendar_count,
            "due_automations": due_automation_count,
            "overdue_automations": overdue_automation_count,
            "stale_goals": len(stale_goal_items),
            "focus_minutes": focus_minutes,
            "meeting_minutes": meeting_minutes,
        },
        "focus_items": focus_items,
        "timeline": timeline,
    }
