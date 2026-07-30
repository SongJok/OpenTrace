"""Projects, assistant profiles, goals and scheduled tasks for the v2 product."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import get_accessible_data_source
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.assistant_profiles import BUILT_IN_ASSISTANT_PROFILES
from infra.errors import AppException, ErrorCodes
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    AlertRule,
    AssistantProfile,
    CalendarEvent,
    ChatSession,
    GoalCheckpoint,
    GoalRun,
    Project,
    ResponseRecord,
    TaskDefinition,
    TaskNotification,
    TaskRun,
    User,
)

router = APIRouter()


class ProjectPayload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=8000)
    instructions: str = Field(default="", max_length=16_000)
    memory_mode: str = Field(default="default", pattern="^(default|project_only)$")
    assistant_profile_id: str | None = None
    data_source_ids: list[str] = Field(default_factory=list)


class AssistantProfilePayload(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    personality: str = Field(
        default="none", pattern="^(none|friendly|pragmatic|cute|romantic|funny)$"
    )
    instructions: str = Field(default="", max_length=16_000)
    default_model_profile: str = Field(default="auto", pattern="^(auto|fast|deep)$")
    tool_policy: dict[str, Any] = Field(default_factory=dict)
    memory_policy: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False


class GoalPayload(BaseModel):
    objective: str = Field(min_length=3, max_length=20_000)
    success_criteria: str = Field(default="", max_length=10_000)
    project_id: str | None = None
    conversation_id: str | None = None
    execution_profile: str = Field(default="deep", pattern="^(auto|fast|deep)$")


class GoalUpdatePayload(BaseModel):
    objective: str | None = Field(default=None, min_length=3, max_length=20_000)
    success_criteria: str | None = Field(default=None, max_length=10_000)


class ScheduledTaskPayload(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    prompt: str = Field(min_length=3, max_length=20_000)
    rrule: str = Field(min_length=5, max_length=512)
    timezone: str = Field(default="UTC", max_length=64)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    enabled: bool = False
    requires_confirmation: bool = True


class SchedulePreviewPayload(BaseModel):
    expression: str | None = Field(default=None, min_length=2, max_length=500)
    rrule: str | None = Field(default=None, min_length=5, max_length=512)
    timezone: str = Field(default="UTC", max_length=64)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    count: int = Field(default=5, ge=1, le=10)


def _scope(request: Request, user: User) -> tuple[str, str]:
    meta = build_tenant_metadata(request, user_id=user.id)
    return str(meta.get("tenant_id") or "default"), str(meta.get("workspace_id") or "default")


def _project(row: Project) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "instructions": row.instructions,
        "assistant_profile_id": row.assistant_profile_id,
        "memory_mode": row.memory_mode,
        "data_source_ids": list(row.data_source_ids or []),
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _profile(row: AssistantProfile) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "personality": row.personality,
        "instructions": row.instructions,
        "default_model_profile": row.default_model_profile,
        "tool_policy": dict(row.tool_policy or {}),
        "memory_policy": dict(row.memory_policy or {}),
        "built_in": row.built_in,
        "is_default": row.is_default,
    }


async def _seed_profiles(db: AsyncSession, user: User, tenant_id: str, workspace_id: str) -> None:
    rows = (
        (
            await db.execute(
                select(AssistantProfile).where(
                    AssistantProfile.user_id == user.id,
                    AssistantProfile.tenant_id == tenant_id,
                    AssistantProfile.workspace_id == workspace_id,
                )
            )
        )
        .scalars()
        .all()
    )
    by_name = {row.name: row for row in rows}
    has_default = any(row.is_default for row in rows)
    changed = False
    for index, (name, personality) in enumerate(BUILT_IN_ASSISTANT_PROFILES):
        existing = by_name.get(name)
        if existing:
            # 兼容升级前已由用户创建的同名角色，避免唯一约束阻断内置角色补齐。
            if not existing.built_in:
                existing.built_in = True
                existing.personality = personality
                changed = True
            continue
        db.add(
            AssistantProfile(
                id=str(uuid.uuid4()),
                user_id=user.id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                name=name,
                personality=personality,
                built_in=True,
                is_default=index == 0 and not has_default,
            )
        )
        changed = True
    if changed:
        await db.commit()


async def _validate_project_bindings(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    assistant_profile_id: str | None,
    data_source_ids: list[str],
) -> None:
    if assistant_profile_id:
        profile = await db.scalar(
            select(AssistantProfile.id).where(
                AssistantProfile.id == assistant_profile_id,
                AssistantProfile.user_id == user_id,
                AssistantProfile.tenant_id == tenant_id,
                AssistantProfile.workspace_id == workspace_id,
            )
        )
        if profile is None:
            raise AppException(
                ErrorCodes.RESOURCE_NOT_FOUND.code,
                message="助手角色不存在或无权限",
            )
    tenant_metadata = {"tenant_id": tenant_id, "workspace_id": workspace_id}
    for source_id in dict.fromkeys(data_source_ids):
        source = await get_accessible_data_source(
            db,
            user_id=user_id,
            tenant_metadata=tenant_metadata,
            data_source_id=source_id,
            required_permission="view",
        )
        if source is None:
            raise AppException(
                ErrorCodes.RESOURCE_NOT_FOUND.code,
                message="数据源不存在或无权限",
            )


@router.get("/projects")
async def list_projects(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    rows = (
        (
            await db.execute(
                select(Project)
                .where(
                    Project.user_id == current_user.id,
                    Project.tenant_id == tenant_id,
                    Project.workspace_id == workspace_id,
                    Project.archived_at.is_(None),
                )
                .order_by(Project.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_project(row) for row in rows]}


@router.post("/projects")
async def create_project(
    request: Request,
    payload: ProjectPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    await _validate_project_bindings(
        db,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        assistant_profile_id=payload.assistant_profile_id,
        data_source_ids=payload.data_source_ids,
    )
    row = Project(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        **payload.model_dump(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _project(row)


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: str,
    request: Request,
    payload: ProjectPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    row = await db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == current_user.id,
            Project.tenant_id == tenant_id,
            Project.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Project 不存在")
    await _validate_project_bindings(
        db,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        assistant_profile_id=payload.assistant_profile_id,
        data_source_ids=payload.data_source_ids,
    )
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    await db.commit()
    return _project(row)


@router.delete("/projects/{project_id}")
async def archive_project(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    row = await db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == current_user.id,
            Project.tenant_id == tenant_id,
            Project.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Project 不存在")
    row.archived_at = datetime.now(UTC)
    await db.commit()
    return {"id": project_id, "archived": True}


@router.get("/assistant-profiles")
async def list_assistant_profiles(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    await _seed_profiles(db, current_user, tenant_id, workspace_id)
    rows = (
        (
            await db.execute(
                select(AssistantProfile)
                .where(
                    AssistantProfile.user_id == current_user.id,
                    AssistantProfile.tenant_id == tenant_id,
                    AssistantProfile.workspace_id == workspace_id,
                )
                .order_by(AssistantProfile.built_in.desc(), AssistantProfile.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_profile(row) for row in rows]}


@router.post("/assistant-profiles")
async def create_assistant_profile(
    request: Request,
    payload: AssistantProfilePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    if payload.is_default:
        rows = (
            (
                await db.execute(
                    select(AssistantProfile).where(
                        AssistantProfile.user_id == current_user.id,
                        AssistantProfile.tenant_id == tenant_id,
                        AssistantProfile.workspace_id == workspace_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for item in rows:
            item.is_default = False
    row = AssistantProfile(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        **payload.model_dump(),
    )
    db.add(row)
    await db.commit()
    return _profile(row)


@router.patch("/assistant-profiles/{profile_id}")
async def update_assistant_profile(
    profile_id: str,
    request: Request,
    payload: AssistantProfilePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    row = await db.scalar(
        select(AssistantProfile).where(
            AssistantProfile.id == profile_id,
            AssistantProfile.user_id == current_user.id,
            AssistantProfile.tenant_id == tenant_id,
            AssistantProfile.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="助手角色不存在")
    if row.built_in and payload.name != row.name:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="内置角色不能重命名")
    if payload.is_default:
        others = (
            (
                await db.execute(
                    select(AssistantProfile).where(
                        AssistantProfile.user_id == current_user.id,
                        AssistantProfile.tenant_id == tenant_id,
                        AssistantProfile.workspace_id == workspace_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for item in others:
            item.is_default = item.id == row.id
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    await db.commit()
    return _profile(row)


@router.delete("/assistant-profiles/{profile_id}")
async def delete_assistant_profile(
    profile_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    row = await db.scalar(
        select(AssistantProfile).where(
            AssistantProfile.id == profile_id,
            AssistantProfile.user_id == current_user.id,
            AssistantProfile.tenant_id == tenant_id,
            AssistantProfile.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="助手角色不存在")
    if row.built_in:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="内置角色不能删除")
    await db.delete(row)
    await db.commit()
    return {"id": profile_id, "deleted": True}


@router.get("/goals")
async def list_goals(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    rows = (
        (
            await db.execute(
                select(GoalRun)
                .where(
                    GoalRun.user_id == current_user.id,
                    GoalRun.tenant_id == tenant_id,
                    GoalRun.workspace_id == workspace_id,
                )
                .order_by(GoalRun.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_goal(row) for row in rows]}


@router.post("/goals")
async def create_goal(
    request: Request,
    payload: GoalPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from gateway.api_gateway.routers.responses import (
        OpenTraceOptions,
        ResponseCreateRequest,
        create_response,
    )

    tenant_id, workspace_id = _scope(request, current_user)
    if payload.project_id:
        project = await db.scalar(
            select(Project.id).where(
                Project.id == payload.project_id,
                Project.user_id == current_user.id,
                Project.tenant_id == tenant_id,
                Project.workspace_id == workspace_id,
                Project.archived_at.is_(None),
            )
        )
        if project is None:
            raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Project 不存在或无权限")
    if payload.conversation_id:
        conversation = await db.scalar(
            select(ChatSession.id).where(
                ChatSession.id == payload.conversation_id,
                ChatSession.user_id == current_user.id,
                ChatSession.tenant_id == tenant_id,
                ChatSession.workspace_id == workspace_id,
                ChatSession.is_temporary.is_(False),
            )
        )
        if conversation is None:
            raise AppException(
                ErrorCodes.RESOURCE_NOT_FOUND.code,
                message="Conversation 不存在、无权限或为临时对话",
            )
    row = GoalRun(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=payload.project_id,
        conversation_id=payload.conversation_id,
        objective=payload.objective,
        success_criteria=payload.success_criteria,
        status="queued",
        plan={"steps": [], "success_criteria": payload.success_criteria},
    )
    db.add(row)
    await db.flush()
    result = await create_response(
        request,
        ResponseCreateRequest(
            input=payload.objective,
            conversation=payload.conversation_id,
            background=True,
            opentrace=OpenTraceOptions(
                project_id=payload.project_id,
                goal_id=row.id,
                execution_profile=payload.execution_profile,
            ),
        ),
        f"goal:{row.id}:initial",
        current_user,
        db,
    )
    row.response_id = str(result.get("id") or "")
    row.conversation_id = str(result.get("conversation_id") or row.conversation_id or "") or None
    await db.commit()
    await db.refresh(row)
    return _goal(row)


@router.get("/goals/{goal_id}")
async def get_goal(
    goal_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    row = await db.scalar(
        select(GoalRun).where(
            GoalRun.id == goal_id,
            GoalRun.user_id == current_user.id,
            GoalRun.tenant_id == tenant_id,
            GoalRun.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Goal 不存在")
    checkpoints = (
        (
            await db.execute(
                select(GoalCheckpoint)
                .where(GoalCheckpoint.goal_id == goal_id)
                .order_by(GoalCheckpoint.step_number)
            )
        )
        .scalars()
        .all()
    )
    return {
        **_goal(row),
        "checkpoints": [
            {
                "id": item.id,
                "step_number": item.step_number,
                "status": item.status,
                "summary": item.summary,
                "state": item.state,
            }
            for item in checkpoints
        ],
    }


@router.patch("/goals/{goal_id}")
async def update_goal(
    goal_id: str,
    request: Request,
    payload: GoalUpdatePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    row = await db.scalar(
        select(GoalRun).where(
            GoalRun.id == goal_id,
            GoalRun.user_id == current_user.id,
            GoalRun.tenant_id == tenant_id,
            GoalRun.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Goal 不存在")
    if payload.objective is not None:
        row.objective = payload.objective
    if payload.success_criteria is not None:
        row.success_criteria = payload.success_criteria
    await db.commit()
    await db.refresh(row)
    return _goal(row)


@router.post("/goals/{goal_id}/{action}")
async def goal_action(
    goal_id: str,
    action: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if action not in {"pause", "resume", "cancel"}:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Goal 操作不受支持")
    tenant_id, workspace_id = _scope(request, current_user)
    row = await db.scalar(
        select(GoalRun).where(
            GoalRun.id == goal_id,
            GoalRun.user_id == current_user.id,
            GoalRun.tenant_id == tenant_id,
            GoalRun.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Goal 不存在")
    if action in {"pause", "cancel"}:
        row.status = "paused" if action == "pause" else "cancelled"
        if row.response_id:
            response = await db.get(ResponseRecord, row.response_id)
            if response and response.status not in {"completed", "failed", "cancelled"}:
                response.status = "cancelled"
    else:
        from gateway.api_gateway.routers.responses import (
            OpenTraceOptions,
            ResponseCreateRequest,
            create_response,
        )

        result = await create_response(
            request,
            ResponseCreateRequest(
                input=row.objective,
                conversation=row.conversation_id,
                background=True,
                opentrace=OpenTraceOptions(
                    project_id=row.project_id, goal_id=row.id, execution_profile="deep"
                ),
            ),
            f"goal:{row.id}:resume:{uuid.uuid4().hex}",
            current_user,
            db,
        )
        row.response_id = str(result.get("id") or "")
        row.status = "queued"
    await db.commit()
    await db.refresh(row)
    return _goal(row)


def _goal(row: GoalRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "objective": row.objective,
        "success_criteria": row.success_criteria,
        "status": row.status,
        "project_id": row.project_id,
        "conversation_id": row.conversation_id,
        "plan": dict(row.plan or {}),
        "current_step": row.current_step,
        "response_id": row.response_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _validate_schedule(rrule_value: str, timezone_name: str) -> None:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="无效时区") from exc
    try:
        from dateutil.rrule import rrulestr  # type: ignore[import-untyped]

        rrulestr(rrule_value, dtstart=datetime.now(ZoneInfo(timezone_name)))
    except Exception as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="无效 RRULE") from exc


def _normalize_schedule_window(
    starts_at: datetime | None,
    ends_at: datetime | None,
    timezone_name: str,
) -> tuple[datetime | None, datetime | None]:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="无效时区") from exc

    def _normalize(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        localized = value.replace(tzinfo=zone) if value.tzinfo is None else value
        return localized.astimezone(UTC)

    normalized_start = _normalize(starts_at)
    normalized_end = _normalize(ends_at)
    if normalized_start and normalized_end and normalized_end <= normalized_start:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="结束时间必须晚于开始时间")
    return normalized_start, normalized_end


@router.get("/scheduled-tasks")
async def list_scheduled_tasks(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    rows = (
        (
            await db.execute(
                select(TaskDefinition)
                .where(
                    TaskDefinition.user_id == current_user.id,
                    TaskDefinition.tenant_id == tenant_id,
                    TaskDefinition.workspace_id == workspace_id,
                )
                .order_by(TaskDefinition.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_scheduled_task(row) for row in rows]}


@router.post("/scheduled-tasks/preview")
async def preview_scheduled_task(
    payload: SchedulePreviewPayload,
    current_user: User = Depends(get_current_user),
):
    from infra.responses.scheduler import next_occurrences, parse_schedule_expression

    try:
        if payload.rrule:
            rrule_value = payload.rrule.strip()
        elif payload.expression:
            rrule_value = parse_schedule_expression(payload.expression)
        else:
            raise ValueError("missing schedule")
        _validate_schedule(rrule_value, payload.timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message="无法可靠解析该时间表达，请明确写出例如“每天 09:00”或“每周一 10:30”。",
        ) from exc
    starts_at, ends_at = _normalize_schedule_window(
        payload.starts_at, payload.ends_at, payload.timezone
    )
    upcoming = next_occurrences(
        rrule_value,
        payload.timezone,
        starts_at=starts_at,
        ends_at=ends_at,
        limit=payload.count,
    )
    return {
        "expression": payload.expression,
        "rrule": rrule_value,
        "timezone": payload.timezone,
        "starts_at": starts_at.isoformat() if starts_at else None,
        "ends_at": ends_at.isoformat() if ends_at else None,
        "next_run_at": upcoming[0].isoformat() if upcoming else None,
        "next_run_times": [item.isoformat() for item in upcoming],
        "requires_confirmation": True,
    }


@router.post("/scheduled-tasks")
async def create_scheduled_task(
    request: Request,
    payload: ScheduledTaskPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _validate_schedule(payload.rrule, payload.timezone)
    starts_at, ends_at = _normalize_schedule_window(
        payload.starts_at, payload.ends_at, payload.timezone
    )
    tenant_id, workspace_id = _scope(request, current_user)
    if payload.project_id:
        project = await db.scalar(
            select(Project.id).where(
                Project.id == payload.project_id,
                Project.user_id == current_user.id,
                Project.tenant_id == tenant_id,
                Project.workspace_id == workspace_id,
                Project.archived_at.is_(None),
            )
        )
        if project is None:
            raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Project 不存在或无权限")
    if payload.conversation_id:
        conversation = await db.scalar(
            select(ChatSession.id).where(
                ChatSession.id == payload.conversation_id,
                ChatSession.user_id == current_user.id,
                ChatSession.tenant_id == tenant_id,
                ChatSession.workspace_id == workspace_id,
                ChatSession.is_temporary.is_(False),
            )
        )
        if conversation is None:
            raise AppException(
                ErrorCodes.RESOURCE_NOT_FOUND.code,
                message="Conversation 不存在、无权限或为临时对话",
            )
    from infra.responses.scheduler import next_occurrence

    row = TaskDefinition(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        title=payload.title,
        description=payload.prompt,
        trigger_type="rrule",
        trigger_config_json=json.dumps(
            {
                "rrule": payload.rrule,
                "timezone": payload.timezone,
                "starts_at": starts_at.isoformat() if starts_at else None,
                "ends_at": ends_at.isoformat() if ends_at else None,
            }
        ),
        rrule=payload.rrule,
        timezone=payload.timezone,
        project_id=payload.project_id,
        conversation_id=payload.conversation_id,
        requires_confirmation=payload.requires_confirmation,
        status="active" if payload.enabled else "draft",
        next_run_at=(
            next_occurrence(
                payload.rrule,
                payload.timezone,
                starts_at=starts_at,
                ends_at=ends_at,
            )
            if payload.enabled
            else None
        ),
    )
    db.add(row)
    await db.commit()
    return _scheduled_task(row)


@router.get("/scheduled-tasks/{task_id}")
async def get_scheduled_task(
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    row = await db.scalar(
        select(TaskDefinition).where(
            TaskDefinition.id == task_id,
            TaskDefinition.user_id == current_user.id,
            TaskDefinition.tenant_id == tenant_id,
            TaskDefinition.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="定时任务不存在")
    runs = (
        (
            await db.execute(
                select(TaskRun)
                .where(TaskRun.task_id == task_id)
                .order_by(TaskRun.started_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return {
        **_scheduled_task(row),
        "runs": [
            {
                "id": run.id,
                "status": run.status,
                "response_id": run.response_id,
                "scheduled_for": run.scheduled_for.isoformat() if run.scheduled_for else None,
                "output": run.output,
                "error": run.error,
            }
            for run in runs
        ],
    }


@router.post("/scheduled-tasks/{task_id}/actions/{action}")
async def scheduled_task_action(
    task_id: str,
    action: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from infra.responses.scheduler import next_occurrence, task_schedule_bounds

    if action not in {"enable", "pause", "cancel"}:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="定时任务操作不受支持")
    tenant_id, workspace_id = _scope(request, current_user)
    row = await db.scalar(
        select(TaskDefinition).where(
            TaskDefinition.id == task_id,
            TaskDefinition.user_id == current_user.id,
            TaskDefinition.tenant_id == tenant_id,
            TaskDefinition.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="定时任务不存在")
    starts_at, ends_at = task_schedule_bounds(row)
    row.status = {"enable": "active", "pause": "paused", "cancel": "cancelled"}[action]
    row.next_run_at = (
        next_occurrence(
            row.rrule or "",
            row.timezone,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        if action == "enable" and row.rrule
        else None
    )
    if action == "enable" and row.next_run_at is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="任务有效期内没有可执行时间")
    await db.commit()
    return _scheduled_task(row)


@router.post("/scheduled-tasks/{task_id}/run")
async def run_scheduled_task(
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """立即入队一次手动运行，不改变原有周期。"""
    from infra.responses.scheduler import queue_task_run

    tenant_id, workspace_id = _scope(request, current_user)
    row = await db.scalar(
        select(TaskDefinition).where(
            TaskDefinition.id == task_id,
            TaskDefinition.user_id == current_user.id,
            TaskDefinition.tenant_id == tenant_id,
            TaskDefinition.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="定时任务不存在")
    if row.status == "cancelled":
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="已取消的任务不能运行")
    run = await queue_task_run(
        db,
        row,
        scheduled_for=datetime.now(UTC),
        trigger="manual",
    )
    await db.commit()
    if run is None:
        raise AppException(ErrorCodes.RESOURCE_EXISTS.code, message="任务正在入队，请稍后查看")
    return {
        "id": run.id,
        "task_id": run.task_id,
        "status": run.status,
        "response_id": run.response_id,
        "scheduled_for": run.scheduled_for.isoformat() if run.scheduled_for else None,
    }


def _scheduled_task(row: TaskDefinition) -> dict[str, Any]:
    try:
        trigger_config = json.loads(getattr(row, "trigger_config_json", "{}") or "{}")
    except (TypeError, ValueError):
        trigger_config = {}
    return {
        "id": row.id,
        "title": row.title,
        "prompt": row.description,
        "rrule": row.rrule,
        "timezone": row.timezone,
        "starts_at": trigger_config.get("starts_at"),
        "ends_at": trigger_config.get("ends_at"),
        "status": row.status,
        "project_id": row.project_id,
        "conversation_id": row.conversation_id,
        "requires_confirmation": row.requires_confirmation,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
        "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
    }


def _owned_notification_subjects(
    *,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
):
    return (
        select(TaskDefinition.id)
        .where(
            TaskDefinition.user_id == user_id,
            TaskDefinition.tenant_id == tenant_id,
            TaskDefinition.workspace_id == workspace_id,
        )
        .union(
            select(AlertRule.id).where(
                AlertRule.user_id == user_id,
                AlertRule.tenant_id == tenant_id,
                AlertRule.workspace_id == workspace_id,
            ),
            select(CalendarEvent.id).where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.tenant_id == tenant_id,
                CalendarEvent.workspace_id == workspace_id,
            ),
        )
    )


@router.get("/notifications")
async def list_notifications(
    request: Request,
    unread_only: bool = False,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    owned_subjects = _owned_notification_subjects(
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    base = select(TaskNotification).where(
        TaskNotification.user_id == current_user.id,
        TaskNotification.task_id.in_(owned_subjects),
    )
    if unread_only:
        base = base.where(TaskNotification.read.is_(False))
    rows = (
        (
            await db.execute(
                base.order_by(TaskNotification.created_at.desc()).limit(max(1, min(limit, 200)))
            )
        )
        .scalars()
        .all()
    )
    unread_count = await db.scalar(
        select(func.count(TaskNotification.id)).where(
            TaskNotification.user_id == current_user.id,
            TaskNotification.task_id.in_(owned_subjects),
            TaskNotification.read.is_(False),
        )
    )
    alert_ids = set(
        (
            await db.execute(
                select(AlertRule.id).where(
                    AlertRule.user_id == current_user.id,
                    AlertRule.tenant_id == tenant_id,
                    AlertRule.workspace_id == workspace_id,
                )
            )
        )
        .scalars()
        .all()
    )
    calendar_ids = set(
        (
            await db.execute(
                select(CalendarEvent.id).where(
                    CalendarEvent.user_id == current_user.id,
                    CalendarEvent.tenant_id == tenant_id,
                    CalendarEvent.workspace_id == workspace_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        "unread_count": int(unread_count or 0),
        "items": [
            {
                "id": row.id,
                "task_id": row.task_id,
                "run_id": row.run_id,
                "kind": (
                    "alert"
                    if row.task_id in alert_ids
                    else "calendar" if row.task_id in calendar_ids else "scheduled_task"
                ),
                "level": row.level,
                "title": row.title,
                "body": row.body,
                "read": bool(row.read),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


@router.post("/notifications/{notification_id}/read")
async def read_notification(
    notification_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    owned_subjects = _owned_notification_subjects(
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    row = await db.scalar(
        select(TaskNotification).where(
            TaskNotification.id == notification_id,
            TaskNotification.user_id == current_user.id,
            TaskNotification.task_id.in_(owned_subjects),
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="通知不存在")
    row.read = True
    await db.commit()
    return {"id": row.id, "read": True}


@router.post("/notifications/read-all")
async def read_all_notifications(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    owned_subjects = _owned_notification_subjects(
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    result = await db.execute(
        update(TaskNotification)
        .where(
            TaskNotification.user_id == current_user.id,
            TaskNotification.task_id.in_(owned_subjects),
            TaskNotification.read.is_(False),
        )
        .values(read=True)
    )
    await db.commit()
    return {"updated": int(result.rowcount or 0)}
