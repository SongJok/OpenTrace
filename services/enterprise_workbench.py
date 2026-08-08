"""企业 AI 工作台聚合服务。

该模块只读取 PostgreSQL 事实状态，将 Responses、Goal、审批、知识、数据源、
定时任务和预警投影为员工可执行的统一工作入口。所有查询必须保留用户、租户和
工作区边界，不能依赖 Redis 或前端二次过滤实现隔离。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.config.constants import DEFAULT_TIMEZONE
from infra.security.resource_scope import accessible_data_sources_statement
from infra.storage.models import (
    AlertEvent,
    AlertRule,
    AssistantProfile,
    CalendarEvent,
    ChatSession,
    EnterpriseSkill,
    GoalRun,
    KnowledgeSource,
    Project,
    ResponseApproval,
    ResponseRecord,
    TaskDefinition,
    TaskNotification,
    User,
    UserSkillInstallation,
)
from knowledge.access import (
    accessible_source_predicate,
    classification_allows,
    resolve_access_context,
)
from knowledge.governance import knowledge_governance_health
from services.calendar import list_calendar_events, local_day_window
from services.enterprise_cognition import load_enterprise_context
from services.enterprise_scenarios import apply_organization_templates, build_enterprise_scenarios
from services.enterprise_workbench_templates import resolve_user_workbench_templates
from services.workbench_portfolio import build_workbench_portfolio
from services.workbench_pulse import (
    build_workbench_operating_pulse,
    rank_workbench_actions,
)

ACTIVE_RESPONSE_STATUSES = {"queued", "in_progress", "requires_action"}
ACTIVE_GOAL_STATUSES = {"queued", "in_progress", "requires_action", "paused"}
FAILED_RESPONSE_STATUSES = {"failed", "incomplete"}
DEFAULT_CONVERSATION_TITLES = {"new conversation", "新对话", "新会话"}
WORKBENCH_RESPONSE_CANDIDATE_LIMIT = 500


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
    cognitive_entity_count: int = 0,
    published_company_context: bool = False,
) -> dict[str, Any]:
    """生成可解释的企业 AI 就绪度，而不是黑盒总分。"""

    configured_projects = [row for row in projects if (row.instructions or "").strip()]
    bound_projects = [row for row in projects if row.data_source_ids]
    custom_profiles = [row for row in profiles if not row.built_in]
    active_data_sources = [row for row in data_sources if getattr(row, "status", None) == "active"]
    active_goals = [row for row in goals if row.status in ACTIVE_GOAL_STATUSES]

    context_score = min(
        100,
        10
        + (30 if published_company_context else 0)
        + (15 if cognitive_entity_count > 1 else 0)
        + (20 if projects else 0)
        + (15 if configured_projects else 0)
        + (5 if bound_projects else 0)
        + (5 if custom_profiles else 0),
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
    if not published_company_context:
        blockers.append(
            {
                "code": "enterprise_cognition_missing",
                "title": "发布公司基础认知",
                "description": "建立公司使命、业务、术语和治理来源，让每次问答理解企业语境。",
                "route": "/enterprise-admin",
            }
        )
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


def _conversation_route(conversation_id: str) -> str:
    return f"/chat?conversation={conversation_id}"


def _work_action(status: str) -> tuple[str, str]:
    if status == "requires_action":
        return "approval", "处理审批"
    if status in {"queued", "in_progress"}:
        return "monitor", "查看进度"
    if status in FAILED_RESPONSE_STATUSES:
        return "retry", "检查并重试"
    if status == "paused":
        return "resume", "恢复工作"
    if status == "completed":
        return "continue", "继续工作"
    return "review", "查看记录"


def _work_status(response_status: str, goal: Any | None) -> str:
    if response_status in ACTIVE_RESPONSE_STATUSES | FAILED_RESPONSE_STATUSES:
        return response_status
    if goal is not None and str(goal.status) in ACTIVE_GOAL_STATUSES:
        return str(goal.status)
    return response_status


def _work_title(session: Any, fallback: str) -> str:
    for candidate in (
        getattr(session, "display_title", None),
        getattr(session, "title", None),
    ):
        title = _bounded_text(candidate, limit=100)
        if title and title.casefold() not in DEFAULT_CONVERSATION_TITLES:
            return title
    return fallback or "AI 工作"


def build_workbench_activity(
    *,
    responses: list[Any],
    goals: list[Any],
    sessions: list[Any],
    projects: list[Any],
    limit: int,
) -> list[dict[str, Any]]:
    """按持久会话合并最近工作，并给出确定性的下一步。"""

    session_by_id = {str(row.id): row for row in sessions}
    project_names = {str(row.id): str(row.name) for row in projects}
    goals_by_id = {str(row.id): row for row in goals}
    goals_by_conversation: dict[str, Any] = {}
    for row in goals:
        if getattr(row, "conversation_id", None):
            goals_by_conversation.setdefault(str(row.conversation_id), row)
    seen_conversations: set[str] = set()
    activity: list[dict[str, Any]] = []

    for response in responses:
        conversation_id = str(response.conversation_id)
        session = session_by_id.get(conversation_id)
        if session is None or conversation_id in seen_conversations:
            continue
        seen_conversations.add(conversation_id)
        goal = (
            goals_by_id.get(str(response.goal_id)) if getattr(response, "goal_id", None) else None
        )
        goal = goal or goals_by_conversation.get(conversation_id)
        status = _work_status(str(response.status), goal)
        project_id = getattr(goal, "project_id", None) or getattr(session, "project_id", None)
        project_name = project_names.get(str(project_id)) if project_id else None
        request_title = _bounded_text((response.request_payload or {}).get("input"))
        fallback_title = _bounded_text(getattr(goal, "objective", "")) or request_title
        action, action_label = _work_action(status)
        updated_at = max(
            value
            for value in (response.updated_at, getattr(goal, "updated_at", None))
            if value is not None
        )
        activity.append(
            {
                "id": str(goal.id) if goal is not None else str(response.id),
                "type": "goal" if goal is not None else "response",
                "status": status,
                "title": _work_title(session, fallback_title),
                "description": (
                    f"Goal · 检查点 {goal.current_step}"
                    if goal is not None
                    else f"Response · 尝试 {response.attempt_count}/{response.max_attempts}"
                ),
                "route": _conversation_route(conversation_id),
                "action": action,
                "action_label": action_label,
                "conversation_id": conversation_id,
                "response_id": str(response.id),
                "goal_id": str(goal.id) if goal is not None else None,
                "project_id": str(project_id) if project_id else None,
                "project_name": project_name,
                "created_at": _iso(updated_at),
            }
        )

    for goal in goals:
        goal_conversation_id = str(goal.conversation_id) if goal.conversation_id else None
        if goal_conversation_id and goal_conversation_id in seen_conversations:
            continue
        if goal_conversation_id and goal_conversation_id not in session_by_id:
            continue
        if goal_conversation_id:
            seen_conversations.add(goal_conversation_id)
        project_id = getattr(goal, "project_id", None)
        action, action_label = _work_action(str(goal.status))
        activity.append(
            {
                "id": str(goal.id),
                "type": "goal",
                "status": str(goal.status),
                "title": _work_title(
                    (session_by_id.get(goal_conversation_id) if goal_conversation_id else None),
                    _bounded_text(goal.objective),
                ),
                "description": f"Goal · 检查点 {goal.current_step}",
                "route": (
                    _conversation_route(goal_conversation_id)
                    if goal_conversation_id
                    else "/work?tab=goals"
                ),
                "action": action,
                "action_label": action_label,
                "conversation_id": goal_conversation_id,
                "response_id": str(goal.response_id) if goal.response_id else None,
                "goal_id": str(goal.id),
                "project_id": str(project_id) if project_id else None,
                "project_name": project_names.get(str(project_id)) if project_id else None,
                "created_at": _iso(goal.updated_at),
            }
        )

    return _sort_by_created_at(activity)[: max(0, limit)]


async def enterprise_workbench_overview(
    db: AsyncSession,
    *,
    user: User,
    tenant_id: str,
    workspace_id: str,
    org_id: str = "default",
    recent_limit: int = 6,
    attention_limit: int = 10,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    """返回当前员工在当前企业空间内的统一工作台投影。"""

    recent_limit = max(3, min(recent_limit, 20))
    attention_limit = max(5, min(attention_limit, 100))
    candidate_limit = max(attention_limit, 50)
    generated_at = datetime.now(UTC)
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
    active_session_ids = (
        select(ChatSession.id)
        .where(
            ChatSession.user_id == user.id,
            ChatSession.tenant_id == tenant_id,
            ChatSession.workspace_id == workspace_id,
            ChatSession.archived_at.is_(None),
            ChatSession.is_temporary.is_(False),
        )
        .scalar_subquery()
    )
    responses = list(
        (
            await db.execute(
                select(ResponseRecord)
                .where(
                    ResponseRecord.user_id == user.id,
                    ResponseRecord.tenant_id == tenant_id,
                    ResponseRecord.workspace_id == workspace_id,
                    ResponseRecord.conversation_id.in_(active_session_ids),
                )
                .order_by(ResponseRecord.updated_at.desc())
                .limit(max(WORKBENCH_RESPONSE_CANDIDATE_LIMIT + 1, recent_limit * 8))
            )
        ).scalars()
    )
    response_candidates_truncated = len(responses) > WORKBENCH_RESPONSE_CANDIDATE_LIMIT
    responses = responses[:WORKBENCH_RESPONSE_CANDIDATE_LIMIT]
    activity_session_ids = {
        str(row.conversation_id) for row in responses if row.conversation_id
    } | {str(row.conversation_id) for row in goals if row.conversation_id}
    sessions = list(
        (
            await db.execute(
                select(ChatSession)
                .where(
                    ChatSession.id.in_(active_session_ids),
                    ChatSession.id.in_(activity_session_ids),
                )
                .order_by(ChatSession.last_active.desc())
            )
        ).scalars()
    )
    response_scope = (
        ResponseRecord.user_id == user.id,
        ResponseRecord.tenant_id == tenant_id,
        ResponseRecord.workspace_id == workspace_id,
        ResponseRecord.conversation_id.in_(active_session_ids),
    )
    pending_approval_count = int(
        await db.scalar(
            select(func.count(ResponseApproval.id))
            .join(ResponseRecord, ResponseApproval.response_id == ResponseRecord.id)
            .where(ResponseApproval.status == "pending", *response_scope)
        )
        or 0
    )
    pending_approval_rows = list(
        (
            await db.execute(
                select(
                    ResponseApproval,
                    ResponseRecord.conversation_id,
                    ChatSession.project_id,
                )
                .join(ResponseRecord, ResponseApproval.response_id == ResponseRecord.id)
                .join(ChatSession, ChatSession.id == ResponseRecord.conversation_id)
                .where(ResponseApproval.status == "pending", *response_scope)
                .order_by(ResponseApproval.created_at.desc())
                .limit(WORKBENCH_RESPONSE_CANDIDATE_LIMIT)
            )
        ).all()
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
                .limit(candidate_limit)
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
    calendar_ids = list(
        (
            await db.execute(
                select(CalendarEvent.id).where(
                    CalendarEvent.user_id == user.id,
                    CalendarEvent.tenant_id == tenant_id,
                    CalendarEvent.workspace_id == workspace_id,
                )
            )
        ).scalars()
    )
    local_date = generated_at.astimezone(ZoneInfo(timezone_name)).date()
    today_start, today_end = local_day_window(local_date, timezone_name)
    today_calendar_events = await list_calendar_events(
        db,
        user_id=user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        start_at=today_start,
        end_at=today_end,
        timezone_name=timezone_name,
        limit=200,
    )
    notification_subject_ids = task_ids + alert_ids + calendar_ids
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
                    .limit(attention_limit)
                )
            ).scalars()
        )

    alert_events: list[AlertEvent] = []
    unacknowledged_alert_count = 0
    critical_alert_count = 0
    if alert_ids:
        alert_scope = (
            AlertEvent.user_id == user.id,
            AlertEvent.rule_id.in_(alert_ids),
            AlertEvent.state == "triggered",
            AlertEvent.acknowledged_at.is_(None),
        )
        unacknowledged_alert_count = int(
            await db.scalar(select(func.count(AlertEvent.id)).where(*alert_scope)) or 0
        )
        critical_alert_count = int(
            await db.scalar(
                select(func.count(AlertEvent.id)).where(
                    *alert_scope, AlertEvent.severity == "critical"
                )
            )
            or 0
        )
        alert_events = list(
            (
                await db.execute(
                    select(AlertEvent)
                    .where(*alert_scope)
                    .order_by(AlertEvent.created_at.desc())
                    .limit(WORKBENCH_RESPONSE_CANDIDATE_LIMIT)
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
    installed_skill_count = int(
        await db.scalar(
            select(func.count(UserSkillInstallation.id)).where(
                UserSkillInstallation.user_id == user.id,
                UserSkillInstallation.tenant_id == tenant_id,
                UserSkillInstallation.workspace_id == workspace_id,
                UserSkillInstallation.status == "installed",
            )
        )
        or 0
    )
    company_skill_classifications = list(
        (
            await db.execute(
                select(EnterpriseSkill.classification).where(
                    EnterpriseSkill.tenant_id == tenant_id,
                    EnterpriseSkill.workspace_id == workspace_id,
                    EnterpriseSkill.status == "published",
                )
            )
        ).scalars()
    )
    company_skill_count = sum(
        1
        for classification in company_skill_classifications
        if classification_allows(knowledge_context.clearance, classification)
    )
    knowledge_health = await knowledge_governance_health(
        db,
        user=user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    cognitive_context = await load_enterprise_context(
        db,
        user_id=user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        org_id=org_id,
        query="公司和部门概况",
    )
    matched_templates, directory_principals = await resolve_user_workbench_templates(
        db,
        user_id=user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        now=generated_at,
    )

    active_goals = [row for row in goals if row.status in ACTIVE_GOAL_STATUSES]
    active_tasks = [row for row in tasks if row.status == "active"]
    active_alerts = [row for row in alerts if row.status == "active"]
    active_data_sources = [row for row in data_sources if getattr(row, "status", None) == "active"]

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
        critical_alert_count=critical_alert_count,
        failed_response_count=failed_response_count,
        knowledge_health=knowledge_health,
        cognitive_entity_count=len(cognitive_context.entities),
        published_company_context=any(
            item.get("entity_type") == "company" for item in cognitive_context.entities
        ),
    )
    scenarios = build_enterprise_scenarios(
        project_count=len(projects),
        published_knowledge_count=published_knowledge_count,
        active_data_source_count=len(active_data_sources),
        installed_skill_count=installed_skill_count,
        company_skill_count=company_skill_count,
        active_goal_count=len(active_goals),
        active_task_count=len(active_tasks),
        active_alert_count=len(active_alerts),
    )
    scenarios = apply_organization_templates(scenarios, matched_templates)

    attention_items: list[dict[str, Any]] = []
    alert_id_set = set(alert_ids)
    calendar_id_set = set(calendar_ids)
    for notification in unread_notification_rows:
        is_alert = notification.task_id in alert_id_set
        is_calendar = notification.task_id in calendar_id_set
        attention_items.append(
            {
                "id": notification.id,
                "type": "notification",
                "severity": notification.level,
                "title": notification.title,
                "description": notification.body or "新的企业主动工作通知等待查看。",
                "route": "/alerts" if is_alert else "/calendar" if is_calendar else "/tasks",
                "resource_id": notification.task_id,
                "created_at": _iso(notification.created_at),
            }
        )
    for approval, conversation_id, _project_id in pending_approval_rows:
        attention_items.append(
            {
                "id": approval.id,
                "type": "approval",
                "severity": "warning",
                "title": f"待审批：{approval.tool_name}",
                "description": f"{approval.side_effect_level} 操作正在等待你的确认。",
                "route": _conversation_route(str(conversation_id)),
                "resource_id": approval.response_id,
                "created_at": _iso(approval.created_at),
            }
        )
    for event in alert_events:
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
                "route": _conversation_route(str(response.conversation_id)),
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
                "created_at": generated_at.isoformat(),
            }
        )
    attention_items = rank_workbench_actions(attention_items, now=generated_at)[:attention_limit]
    operating_pulse = build_workbench_operating_pulse(
        attention_items=attention_items,
        tasks=tasks,
        alerts=alerts,
        goals=goals,
        calendar_events=today_calendar_events,
        timezone_name=timezone_name,
        focus_limit=min(attention_limit, 8),
        now=generated_at,
    )

    recent_activity = build_workbench_activity(
        responses=responses,
        goals=goals,
        sessions=sessions,
        projects=projects,
        limit=recent_limit,
    )
    portfolio = build_workbench_portfolio(
        projects=projects,
        sessions=sessions,
        responses=responses,
        goals=goals,
        pending_approvals=[
            (approval, conversation_id, project_id)
            for approval, conversation_id, project_id in pending_approval_rows
        ],
        tasks=tasks,
        alerts=alerts,
        alert_events=alert_events,
        now=generated_at,
        response_candidate_limit=WORKBENCH_RESPONSE_CANDIDATE_LIMIT,
        response_candidates_truncated=response_candidates_truncated,
    )

    return {
        "generated_at": generated_at.isoformat(),
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
            "unacknowledged_alerts": unacknowledged_alert_count,
            "accessible_data_sources": len(data_sources),
            "knowledge_spaces": len(knowledge_context.accessible_space_ids),
            "published_knowledge": published_knowledge_count,
            "installed_skills": installed_skill_count,
            "company_skills": company_skill_count,
            "available_work_scenarios": sum(
                1 for item in scenarios if item["status"] != "setup_required"
            ),
            "active_work_scenarios": sum(1 for item in scenarios if item["status"] == "active"),
            "enterprise_cognitive_entities": len(cognitive_context.entities),
            "company_context_ready": any(
                item.get("entity_type") == "company" for item in cognitive_context.entities
            ),
        },
        "knowledge_health": knowledge_health,
        "personalization": {
            "applied": bool(matched_templates),
            "templates": matched_templates,
            "principals": directory_principals,
        },
        "operating_pulse": operating_pulse,
        "portfolio": portfolio,
        "scenarios": scenarios,
        "attention_items": attention_items,
        "recent_activity": recent_activity,
    }
