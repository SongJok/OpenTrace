"""企业 AI 工作台聚合服务。

该模块只读取 PostgreSQL 事实状态，将 Responses、Goal、审批、知识、数据源、
定时任务和预警投影为员工可执行的统一工作入口。所有查询必须保留用户、租户和
工作区边界，不能依赖 Redis 或前端二次过滤实现隔离。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.security.resource_scope import accessible_data_sources_statement
from infra.storage.models import (
    AlertEvent,
    AlertRule,
    AssistantProfile,
    GoalRun,
    KnowledgeSource,
    Project,
    ResponseApproval,
    ResponseRecord,
    TaskDefinition,
    TaskNotification,
    User,
)
from knowledge.access import accessible_source_predicate, resolve_access_context
from knowledge.governance import knowledge_governance_health

ACTIVE_RESPONSE_STATUSES = {"queued", "in_progress", "requires_action"}
ACTIVE_GOAL_STATUSES = {"queued", "in_progress", "requires_action", "paused"}
FAILED_RESPONSE_STATUSES = {"failed", "incomplete"}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _bounded_text(value: Any, *, limit: int = 120) -> str:
    if isinstance(value, str):
        text = value
    elif isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                candidate = item.get("text") or item.get("content")
                if isinstance(candidate, str):
                    parts.append(candidate)
        text = " ".join(parts)
    else:
        text = ""
    normalized = " ".join(text.split())
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 1]}…"


def _score_status(score: int) -> str:
    if score >= 85:
        return "ready"
    if score >= 60:
        return "attention"
    return "foundation"


def build_enterprise_readiness(
    *,
    projects: list[Project],
    profiles: list[AssistantProfile],
    goals: list[GoalRun],
    data_sources: list[Any],
    knowledge_space_count: int,
    published_knowledge_count: int,
    active_task_count: int,
    active_alert_count: int,
    pending_approval_count: int,
    critical_alert_count: int,
    failed_response_count: int,
    knowledge_health: dict[str, Any],
) -> dict[str, Any]:
    """生成可解释的企业 AI 就绪度，而不是黑盒总分。"""

    configured_projects = [row for row in projects if (row.instructions or "").strip()]
    bound_projects = [row for row in projects if row.data_source_ids]
    custom_profiles = [row for row in profiles if not row.built_in]
    active_data_sources = [row for row in data_sources if getattr(row, "status", None) == "active"]
    active_goals = [row for row in goals if row.status in ACTIVE_GOAL_STATUSES]

    context_score = min(
        100,
        20
        + (35 if projects else 0)
        + (20 if configured_projects else 0)
        + (15 if bound_projects else 0)
        + (10 if custom_profiles else 0),
    )
    knowledge_score = min(
        100,
        20
        + (30 if knowledge_space_count else 0)
        + (40 if published_knowledge_count else 0)
        + (10 if knowledge_health.get("status") == "healthy" else 0),
    )
    data_score = 100 if active_data_sources else 35
    automation_score = min(
        100,
        25
        + (25 if active_goals else 0)
        + (25 if active_task_count else 0)
        + (25 if active_alert_count else 0),
    )
    governance_score = max(
        0,
        min(
            100,
            int(knowledge_health.get("score", 100))
            - pending_approval_count * 5
            - critical_alert_count * 10
            - failed_response_count * 4,
        ),
    )
    dimensions = {
        "context": context_score,
        "knowledge": knowledge_score,
        "data": data_score,
        "automation": automation_score,
        "governance": governance_score,
    }
    score = round(
        context_score * 0.25
        + knowledge_score * 0.25
        + data_score * 0.20
        + automation_score * 0.15
        + governance_score * 0.15
    )

    blockers: list[dict[str, str]] = []
    if not projects:
        blockers.append(
            {
                "code": "project_context_missing",
                "title": "建立第一个 Project",
                "description": "用 Project 固化业务目标、指令、数据权限和记忆边界。",
                "route": "/work?tab=projects",
            }
        )
    elif not configured_projects:
        blockers.append(
            {
                "code": "project_instructions_missing",
                "title": "补充 Project 指令",
                "description": "明确业务术语、输出规范和决策约束，让 AI 更懂当前团队。",
                "route": "/work?tab=projects",
            }
        )
    if not published_knowledge_count:
        blockers.append(
            {
                "code": "company_knowledge_missing",
                "title": "接入企业知识",
                "description": "投稿制度、流程和业务资料，并经治理流程发布为可信知识。",
                "route": "/documents",
            }
        )
    if not active_data_sources:
        blockers.append(
            {
                "code": "enterprise_data_missing",
                "title": "连接企业数据",
                "description": "接入授权数据源，使 AI 能基于实时业务数据分析和行动。",
                "route": "/databases",
            }
        )
    if not (active_goals or active_task_count or active_alert_count):
        blockers.append(
            {
                "code": "automation_missing",
                "title": "启用一个主动工作流",
                "description": "创建 Goal、定时任务或主动预警，让 AI 从问答走向持续执行。",
                "route": "/work?tab=goals",
            }
        )
    if pending_approval_count:
        blockers.append(
            {
                "code": "approvals_pending",
                "title": f"处理 {pending_approval_count} 个待审批动作",
                "description": "副作用操作必须人工确认后才会继续执行。",
                "route": "/chat",
            }
        )
    if critical_alert_count:
        blockers.append(
            {
                "code": "critical_alerts_pending",
                "title": f"确认 {critical_alert_count} 个关键预警",
                "description": "关键业务异常仍未确认，请及时查看证据并处置。",
                "route": "/alerts",
            }
        )

    return {
        "score": score,
        "status": _score_status(score),
        "dimensions": dimensions,
        "blockers": blockers[:5],
    }


def _sort_by_created_at(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: str(item.get("created_at") or ""), reverse=True)


async def enterprise_workbench_overview(
    db: AsyncSession,
    *,
    user: User,
    tenant_id: str,
    workspace_id: str,
    recent_limit: int = 6,
) -> dict[str, Any]:
    """返回当前员工在当前企业空间内的统一工作台投影。"""

    recent_limit = max(3, min(recent_limit, 20))
    scope = (
        Project.user_id == user.id,
        Project.tenant_id == tenant_id,
        Project.workspace_id == workspace_id,
        Project.archived_at.is_(None),
    )
    projects = list((await db.execute(select(Project).where(*scope))).scalars())
    profiles = list(
        (
            await db.execute(
                select(AssistantProfile).where(
                    AssistantProfile.user_id == user.id,
                    AssistantProfile.tenant_id == tenant_id,
                    AssistantProfile.workspace_id == workspace_id,
                )
            )
        ).scalars()
    )
    goals = list(
        (
            await db.execute(
                select(GoalRun)
                .where(
                    GoalRun.user_id == user.id,
                    GoalRun.tenant_id == tenant_id,
                    GoalRun.workspace_id == workspace_id,
                )
                .order_by(GoalRun.updated_at.desc())
            )
        ).scalars()
    )
    responses = list(
        (
            await db.execute(
                select(ResponseRecord)
                .where(
                    ResponseRecord.user_id == user.id,
                    ResponseRecord.tenant_id == tenant_id,
                    ResponseRecord.workspace_id == workspace_id,
                )
                .order_by(ResponseRecord.updated_at.desc())
                .limit(max(30, recent_limit * 4))
            )
        ).scalars()
    )
    response_scope = (
        ResponseRecord.user_id == user.id,
        ResponseRecord.tenant_id == tenant_id,
        ResponseRecord.workspace_id == workspace_id,
    )
    pending_approval_count = int(
        await db.scalar(
            select(func.count(ResponseApproval.id))
            .join(ResponseRecord, ResponseApproval.response_id == ResponseRecord.id)
            .where(ResponseApproval.status == "pending", *response_scope)
        )
        or 0
    )
    pending_approvals = list(
        (
            await db.execute(
                select(ResponseApproval)
                .join(ResponseRecord, ResponseApproval.response_id == ResponseRecord.id)
                .where(ResponseApproval.status == "pending", *response_scope)
                .order_by(ResponseApproval.created_at.desc())
                .limit(10)
            )
        ).scalars()
    )
    active_response_count = int(
        await db.scalar(
            select(func.count(ResponseRecord.id)).where(
                *response_scope, ResponseRecord.status.in_(ACTIVE_RESPONSE_STATUSES)
            )
        )
        or 0
    )
    failed_response_count = int(
        await db.scalar(
            select(func.count(ResponseRecord.id)).where(
                *response_scope, ResponseRecord.status.in_(FAILED_RESPONSE_STATUSES)
            )
        )
        or 0
    )
    failed_responses = list(
        (
            await db.execute(
                select(ResponseRecord)
                .where(*response_scope, ResponseRecord.status.in_(FAILED_RESPONSE_STATUSES))
                .order_by(ResponseRecord.updated_at.desc())
                .limit(3)
            )
        ).scalars()
    )

    tasks = list(
        (
            await db.execute(
                select(TaskDefinition).where(
                    TaskDefinition.user_id == user.id,
                    TaskDefinition.tenant_id == tenant_id,
                    TaskDefinition.workspace_id == workspace_id,
                )
            )
        ).scalars()
    )
    task_ids = [row.id for row in tasks]
    alerts = list(
        (
            await db.execute(
                select(AlertRule).where(
                    AlertRule.user_id == user.id,
                    AlertRule.tenant_id == tenant_id,
                    AlertRule.workspace_id == workspace_id,
                )
            )
        ).scalars()
    )
    alert_ids = [row.id for row in alerts]
    notification_subject_ids = task_ids + alert_ids
    unread_notifications = 0
    unread_notification_rows: list[TaskNotification] = []
    if notification_subject_ids:
        unread_notifications = int(
            await db.scalar(
                select(func.count(TaskNotification.id)).where(
                    TaskNotification.user_id == user.id,
                    TaskNotification.task_id.in_(notification_subject_ids),
                    TaskNotification.read.is_(False),
                )
            )
            or 0
        )
        unread_notification_rows = list(
            (
                await db.execute(
                    select(TaskNotification)
                    .where(
                        TaskNotification.user_id == user.id,
                        TaskNotification.task_id.in_(notification_subject_ids),
                        TaskNotification.read.is_(False),
                    )
                    .order_by(TaskNotification.created_at.desc())
                    .limit(5)
                )
            ).scalars()
        )

    alert_events: list[AlertEvent] = []
    if alert_ids:
        alert_events = list(
            (
                await db.execute(
                    select(AlertEvent)
                    .where(
                        AlertEvent.user_id == user.id,
                        AlertEvent.rule_id.in_(alert_ids),
                        AlertEvent.state == "triggered",
                        AlertEvent.acknowledged_at.is_(None),
                    )
                    .order_by(AlertEvent.created_at.desc())
                    .limit(50)
                )
            ).scalars()
        )

    data_sources = list(
        (
            await db.execute(
                accessible_data_sources_statement(
                    user_id=user.id,
                    tenant_metadata={"tenant_id": tenant_id, "workspace_id": workspace_id},
                )
            )
        ).scalars()
    )
    knowledge_context = await resolve_access_context(
        db,
        user=user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    published_knowledge_count = int(
        await db.scalar(
            select(func.count(KnowledgeSource.id)).where(
                KnowledgeSource.tenant_id == tenant_id,
                KnowledgeSource.workspace_id == workspace_id,
                KnowledgeSource.status == "published",
                accessible_source_predicate(knowledge_context),
            )
        )
        or 0
    )
    knowledge_health = await knowledge_governance_health(
        db,
        user=user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )

    active_goals = [row for row in goals if row.status in ACTIVE_GOAL_STATUSES]
    active_tasks = [row for row in tasks if row.status == "active"]
    active_alerts = [row for row in alerts if row.status == "active"]
    critical_alerts = [row for row in alert_events if row.severity == "critical"]

    readiness = build_enterprise_readiness(
        projects=projects,
        profiles=profiles,
        goals=goals,
        data_sources=data_sources,
        knowledge_space_count=len(knowledge_context.accessible_space_ids),
        published_knowledge_count=published_knowledge_count,
        active_task_count=len(active_tasks),
        active_alert_count=len(active_alerts),
        pending_approval_count=pending_approval_count,
        critical_alert_count=len(critical_alerts),
        failed_response_count=failed_response_count,
        knowledge_health=knowledge_health,
    )

    attention_items: list[dict[str, Any]] = []
    alert_id_set = set(alert_ids)
    for notification in unread_notification_rows:
        is_alert = notification.task_id in alert_id_set
        attention_items.append(
            {
                "id": notification.id,
                "type": "notification",
                "severity": notification.level,
                "title": notification.title,
                "description": notification.body or "新的企业主动工作通知等待查看。",
                "route": "/alerts" if is_alert else "/tasks",
                "resource_id": notification.task_id,
                "created_at": _iso(notification.created_at),
            }
        )
    for approval in pending_approvals[:5]:
        attention_items.append(
            {
                "id": approval.id,
                "type": "approval",
                "severity": "warning",
                "title": f"待审批：{approval.tool_name}",
                "description": f"{approval.side_effect_level} 操作正在等待你的确认。",
                "route": "/chat",
                "resource_id": approval.response_id,
                "created_at": _iso(approval.created_at),
            }
        )
    for event in alert_events[:5]:
        attention_items.append(
            {
                "id": event.id,
                "type": "alert",
                "severity": event.severity,
                "title": event.summary,
                "description": "关键业务指标已触发规则，等待确认。",
                "route": "/alerts",
                "resource_id": event.rule_id,
                "created_at": _iso(event.created_at),
            }
        )
    for response in failed_responses[:3]:
        attention_items.append(
            {
                "id": response.id,
                "type": "response",
                "severity": "error",
                "title": "AI 工作执行未完成",
                "description": response.error_message or "可进入对话查看执行事件并安全重试。",
                "route": "/chat",
                "resource_id": response.id,
                "created_at": _iso(response.updated_at),
            }
        )
    knowledge_metrics = knowledge_health.get("metrics") or {}
    knowledge_attention = sum(
        int(knowledge_metrics.get(key, 0) or 0)
        for key in ("due_reviews", "blocked_reviews", "unresolved_feedback", "failed_jobs")
    )
    if knowledge_attention:
        attention_items.append(
            {
                "id": "knowledge-governance",
                "type": "knowledge",
                "severity": "warning" if knowledge_health.get("status") != "critical" else "error",
                "title": f"知识治理有 {knowledge_attention} 项待处理",
                "description": "包括到期复审、反馈、阻塞或编排失败，请由治理角色处理。",
                "route": "/knowledge",
                "resource_id": None,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
    attention_items = _sort_by_created_at(attention_items)[:10]

    recent_activity: list[dict[str, Any]] = []
    for response in responses[:recent_limit]:
        recent_activity.append(
            {
                "id": response.id,
                "type": "response",
                "status": response.status,
                "title": _bounded_text((response.request_payload or {}).get("input"))
                or "AI 对话任务",
                "description": f"Responses 主链路 · 尝试 {response.attempt_count}/{response.max_attempts}",
                "route": "/chat",
                "created_at": _iso(response.updated_at),
            }
        )
    for goal in goals[:recent_limit]:
        recent_activity.append(
            {
                "id": goal.id,
                "type": "goal",
                "status": goal.status,
                "title": _bounded_text(goal.objective),
                "description": f"Goal · 当前检查点 {goal.current_step}",
                "route": "/work?tab=goals",
                "created_at": _iso(goal.updated_at),
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {"tenant_id": tenant_id, "workspace_id": workspace_id, "user_id": user.id},
        "readiness": readiness,
        "summary": {
            "projects": len(projects),
            "active_goals": len(active_goals),
            "running_responses": active_response_count,
            "pending_approvals": pending_approval_count,
            "unread_notifications": unread_notifications,
            "scheduled_tasks": len(active_tasks),
            "active_alerts": len(active_alerts),
            "unacknowledged_alerts": len(alert_events),
            "accessible_data_sources": len(data_sources),
            "knowledge_spaces": len(knowledge_context.accessible_space_ids),
            "published_knowledge": published_knowledge_count,
        },
        "knowledge_health": knowledge_health,
        "attention_items": attention_items,
        "recent_activity": _sort_by_created_at(recent_activity)[:recent_limit],
    }
