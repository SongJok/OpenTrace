"""Canonical OpenTrace Responses API.

The HTTP process validates commands, commits durable state and projects
persisted events. Model and tool execution belongs exclusively to the worker.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, cast

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.responses.repository import TERMINAL_STATUSES, add_outbox, append_event
from infra.storage.database import AsyncSessionLocal
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    AssistantProfile,
    Attachment,
    ChatSession,
    DataSource,
    GoalRun,
    Project,
    ResponseEvent,
    ResponseItem,
    ResponseRecord,
    User,
)

router = APIRouter()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        try:
            return _json_safe(value.model_dump(mode="json"))
        except TypeError:
            return _json_safe(value.model_dump())
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _json_safe(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_json_safe(item) for item in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


class ResponseInputItem(BaseModel):
    role: str = Field(default="user", pattern="^(user|assistant|system|developer|tool)$")
    content: str | list[dict[str, Any]]


class OpenTraceOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str | None = None
    assistant_profile_id: str | None = None
    execution_profile: str = Field(default="auto", pattern="^(auto|fast|deep)$")
    memory_mode: str = Field(default="enabled", pattern="^(enabled|disabled|temporary)$")
    enabled_skills: list[str] = Field(default_factory=list)
    data_source_ids: list[str] = Field(default_factory=list)
    attachment_ids: list[str] = Field(default_factory=list, max_length=10)
    goal_id: str | None = None


class ResponseCreateRequest(BaseModel):
    """Responses-compatible core with one namespaced OpenTrace extension."""

    model_config = ConfigDict(extra="forbid")

    input: str | list[ResponseInputItem]
    conversation: str | dict[str, Any] | None = None
    previous_response_id: str | None = None
    parent_response_id: str | None = None
    model: str | None = Field(default=None, max_length=128)
    instructions: str | list[ResponseInputItem] | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_choice: str = Field(default="auto", pattern="^(auto|none|required)$")
    parallel_tool_calls: bool = True
    max_output_tokens: int | None = Field(default=None, ge=1, le=131072)
    truncation: str = Field(default="disabled", pattern="^(disabled|auto)$")
    stream: bool = False
    background: bool = False
    store: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    text: dict[str, Any] = Field(default_factory=dict)
    reasoning: dict[str, Any] = Field(default_factory=lambda: {"summary": "auto"})
    opentrace: OpenTraceOptions = Field(default_factory=OpenTraceOptions)

    @model_validator(mode="before")
    @classmethod
    def migrate_transition_fields(cls, value: Any) -> Any:
        """Keep rolling old/new web instances compatible without publishing old fields."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "conversation_id" in data and "conversation" not in data:
            data["conversation"] = data.pop("conversation_id")
        extension = dict(data.get("opentrace") or {})
        aliases = {
            "execution_profile": "execution_profile",
            "memory_mode": "memory_mode",
            "enabled_skills": "enabled_skills",
            "project_id": "project_id",
            "assistant_profile_id": "assistant_profile_id",
            "attachment_ids": "attachment_ids",
            "goal_id": "goal_id",
        }
        for old, new in aliases.items():
            if old in data:
                extension.setdefault(new, data.pop(old))
        if "data_source_id" in data:
            source = data.pop("data_source_id")
            extension.setdefault("data_source_ids", [source] if source else [])
        # Discard execution controls that belonged to the retired v1 chat pipeline.
        for old in (
            "disabled_skills", "data_source_name", "force_database", "force_mode",
            "execution_mode", "web_enabled", "graph_controls", "tool_permission_token",
            "confirmation_granted", "clarify_context", "clarify_question_id",
            "parent_message_id", "reference_id", "reference_type",
            "state_version", "knowledge",
        ):
            data.pop(old, None)
        data["opentrace"] = extension
        return data

    @property
    def conversation_id(self) -> str | None:
        if isinstance(self.conversation, str):
            return self.conversation
        if isinstance(self.conversation, dict):
            return str(self.conversation.get("id") or "") or None
        return None

    # Read-only transition properties; they are absent from the public schema.
    @property
    def execution_profile(self) -> str:
        return self.opentrace.execution_profile

    @property
    def memory_mode(self) -> str:
        return self.opentrace.memory_mode

    @property
    def enabled_skills(self) -> list[str]:
        return self.opentrace.enabled_skills

    @property
    def data_source_id(self) -> str | None:
        return self.opentrace.data_source_ids[0] if self.opentrace.data_source_ids else None

    @property
    def attachment_ids(self) -> list[str]:
        return self.opentrace.attachment_ids


class ResponseEventOut(BaseModel):
    sequence_number: int
    type: str
    data: dict[str, Any]
    created_at: str


class ResponseRetryRequest(BaseModel):
    input: str | list[ResponseInputItem] | None = None
    stream: bool = True


def extract_user_input(value: str | list[ResponseInputItem] | list[dict[str, Any]]) -> str:
    if isinstance(value, str):
        if value.strip():
            return value.strip()
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="input 不能为空")
    for item in reversed(value):
        role: str
        content: Any
        if isinstance(item, ResponseInputItem):
            role = item.role
            content = item.content
        else:
            item_dict = cast(dict[str, Any], item)
            role = str(item_dict.get("role") or "")
            content = item_dict.get("content")
        if role != "user":
            continue
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            for part in reversed(content):
                if not isinstance(part, dict):
                    continue
                text = part.get("text") or part.get("input_text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
    raise AppException(ErrorCodes.PARAM_INVALID.code, message="input 必须包含非空 user 消息")


def _record_to_dict(
    record: ResponseRecord,
    items: Sequence[ResponseItem] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": record.id,
        "object": "response",
        "status": record.status,
        "conversation": {"id": record.conversation_id},
        "conversation_id": record.conversation_id,
        "previous_response_id": record.parent_response_id,
        "parent_response_id": record.parent_response_id,
        "model": record.model,
        "error": {"code": record.error_code, "message": record.error_message} if record.error_code or record.error_message else None,
        "metadata": _json_safe(dict(record.response_metadata or {})),
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }
    if items is not None:
        payload["output"] = [
            {
                "id": item.id, "type": item.item_type, "role": item.role,
                "content": item.content, "payload": _json_safe(dict(item.payload or {})),
                "sequence_number": item.sequence_number,
            }
            for item in items
        ]
        payload["output_text"] = next(
            (
                item.content or ""
                for item in reversed(items)
                if item.item_type == "message" and item.role == "assistant"
            ),
            "",
        )
    metadata = dict(record.response_metadata or {})
    payload["usage"] = {
        "input_tokens": int(metadata.get("prompt_tokens") or 0),
        "output_tokens": int(metadata.get("completion_tokens") or 0),
        "total_tokens": int(metadata.get("prompt_tokens") or 0)
        + int(metadata.get("completion_tokens") or 0),
    }
    return payload


async def _validate_attachments(
    db: AsyncSession,
    *,
    attachment_ids: list[str],
    session: ChatSession,
    user: User,
) -> None:
    if not attachment_ids:
        return
    rows = (
        await db.execute(
            select(Attachment.id).where(
                Attachment.id.in_(attachment_ids),
                Attachment.user_id == user.id,
                Attachment.session_id == session.id,
                Attachment.status == "active",
            )
        )
    ).scalars().all()
    if set(rows) != set(attachment_ids):
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="附件不存在或不属于当前 Conversation")


async def _load_response(
    db: AsyncSession,
    response_id: str,
    user: User,
    tenant_id: str,
    workspace_id: str,
) -> ResponseRecord:
    row = await db.scalar(
        select(ResponseRecord).where(
            ResponseRecord.id == response_id,
            ResponseRecord.user_id == user.id,
            ResponseRecord.tenant_id == tenant_id,
            ResponseRecord.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Response 不存在")
    return row


async def _ensure_conversation(
    db: AsyncSession,
    *,
    request: ResponseCreateRequest,
    user: User,
    tenant_id: str,
    workspace_id: str,
    org_id: str,
) -> ChatSession:
    conversation_id = request.conversation_id
    if conversation_id:
        session = await db.scalar(
            select(ChatSession).where(
                ChatSession.id == conversation_id,
                ChatSession.user_id == user.id,
                ChatSession.tenant_id == tenant_id,
                ChatSession.workspace_id == workspace_id,
            )
        )
        if session is None:
            raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Conversation 不存在或无权限")
        if session.is_temporary and (request.opentrace.project_id or request.opentrace.goal_id):
            raise AppException(ErrorCodes.PARAM_INVALID.code, message="临时对话不能加入 Project 或 Goal")
        return session
    temporary = request.opentrace.memory_mode == "temporary"
    session = ChatSession(
        id=str(uuid.uuid4()), user_id=user.id, title="New conversation", display_title="New conversation",
        tenant_id=tenant_id, workspace_id=workspace_id, org_id=org_id,
        project_id=request.opentrace.project_id,
        assistant_profile_id=request.opentrace.assistant_profile_id,
        is_temporary=temporary,
        expires_at=datetime.now(UTC) + timedelta(days=30) if temporary else None,
    )
    db.add(session)
    await db.flush()
    return session


async def _validate_opentrace_scope(
    db: AsyncSession,
    *,
    request: ResponseCreateRequest,
    user: User,
    tenant_id: str,
    workspace_id: str,
) -> None:
    extension = request.opentrace
    if extension.memory_mode == "temporary" and (extension.project_id or extension.goal_id):
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="临时对话不能加入 Project 或 Goal")
    if extension.project_id:
        owned = await db.scalar(select(Project.id).where(Project.id == extension.project_id, Project.user_id == user.id, Project.tenant_id == tenant_id, Project.workspace_id == workspace_id))
        if owned is None:
            raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Project 不存在或无权限")
    if extension.assistant_profile_id:
        owned = await db.scalar(select(AssistantProfile.id).where(AssistantProfile.id == extension.assistant_profile_id, AssistantProfile.user_id == user.id, AssistantProfile.tenant_id == tenant_id, AssistantProfile.workspace_id == workspace_id))
        if owned is None:
            raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="助手角色不存在或无权限")
    if extension.goal_id:
        owned = await db.scalar(select(GoalRun.id).where(GoalRun.id == extension.goal_id, GoalRun.user_id == user.id, GoalRun.tenant_id == tenant_id, GoalRun.workspace_id == workspace_id))
        if owned is None:
            raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Goal 不存在或无权限")
    for source_id in extension.data_source_ids:
        owned = await db.scalar(select(DataSource.id).where(DataSource.id == source_id, DataSource.user_id == user.id, DataSource.tenant_id == tenant_id, DataSource.workspace_id == workspace_id))
        if owned is None:
            raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="数据源不存在或无权限")


async def _resolve_parent(
    db: AsyncSession,
    *,
    request: ResponseCreateRequest,
    session: ChatSession,
    user: User,
    tenant_id: str,
) -> str | None:
    parent_id = request.previous_response_id or request.parent_response_id or session.active_response_id
    if not parent_id:
        return None
    parent = await _load_response(
        db, str(parent_id), user, tenant_id, session.workspace_id
    )
    if parent.conversation_id != session.id:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="previous_response_id 不属于当前 Conversation")
    return parent.id


def _sse(event: ResponseEvent) -> str:
    payload = {"sequence_number": event.sequence_number, "type": event.event_type, "data": dict(event.payload or {})}
    return f"id: {event.sequence_number}\nevent: {event.event_type}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


async def _event_stream(response_id: str, *, starting_after: int = -1):
    cursor = starting_after
    while True:
        async with AsyncSessionLocal() as db:
            record = await db.get(ResponseRecord, response_id)
            if record is None:
                return
            events = (
                await db.execute(
                    select(ResponseEvent)
                    .where(ResponseEvent.response_id == response_id, ResponseEvent.sequence_number > cursor)
                    .order_by(ResponseEvent.sequence_number)
                )
            ).scalars().all()
            for event in events:
                cursor = event.sequence_number
                yield _sse(event)
            if record.status in TERMINAL_STATUSES or record.status == "requires_action":
                return
        yield ": keep-alive\n\n"
        await asyncio.sleep(0.25)


async def _wait_for_response(response_id: str, *, timeout_seconds: float = 120.0) -> tuple[ResponseRecord, list[ResponseItem]]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while True:
        async with AsyncSessionLocal() as db:
            record = await db.get(ResponseRecord, response_id)
            if record is None:
                raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Response 不存在")
            if record.status in TERMINAL_STATUSES or record.status == "requires_action" or loop.time() >= deadline:
                items = (
                    await db.execute(
                        select(ResponseItem)
                        .where(ResponseItem.response_id == response_id)
                        .order_by(ResponseItem.sequence_number)
                    )
                ).scalars().all()
                return record, list(items)
        await asyncio.sleep(0.25)


@router.post("/responses")
async def create_response(
    http_request: Request,
    request: ResponseCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = extract_user_input(request.input)
    tenant = build_tenant_metadata(http_request, user_id=current_user.id)
    tenant_id = str(tenant.get("tenant_id") or "default")
    workspace_id = str(tenant.get("workspace_id") or "default")
    org_id = str(tenant.get("org_id") or "default")
    await _validate_opentrace_scope(
        db,
        request=request,
        user=current_user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if idempotency_key:
        existing = await db.scalar(
            select(ResponseRecord).where(
                ResponseRecord.tenant_id == tenant_id,
                ResponseRecord.idempotency_key == idempotency_key,
            )
        )
        if existing:
            if existing.user_id != current_user.id:
                raise AppException(ErrorCodes.PERMISSION_DENIED.code, message="幂等键不可跨用户复用")
            if request.stream:
                return StreamingResponse(_event_stream(existing.id), media_type="text/event-stream")
            items = (await db.execute(select(ResponseItem).where(ResponseItem.response_id == existing.id).order_by(ResponseItem.sequence_number))).scalars().all()
            return _record_to_dict(existing, items)

    session = await _ensure_conversation(
        db, request=request, user=current_user, tenant_id=tenant_id,
        workspace_id=workspace_id, org_id=org_id,
    )
    await _validate_attachments(
        db,
        attachment_ids=request.opentrace.attachment_ids,
        session=session,
        user=current_user,
    )
    if session.is_temporary:
        request.opentrace.memory_mode = "temporary"
    if not request.opentrace.project_id and session.project_id:
        request.opentrace.project_id = session.project_id
    if not request.opentrace.assistant_profile_id and session.assistant_profile_id:
        request.opentrace.assistant_profile_id = session.assistant_profile_id
    parent_id = await _resolve_parent(
        db, request=request, session=session, user=current_user, tenant_id=tenant_id
    )
    response_id = f"resp_{uuid.uuid4().hex}"
    payload = request.model_dump(mode="json")
    record = ResponseRecord(
        id=response_id, conversation_id=session.id, user_id=current_user.id,
        tenant_id=tenant_id, workspace_id=workspace_id, parent_response_id=parent_id,
        request_id=str(getattr(http_request.state, "request_id", "") or uuid.uuid4()),
        idempotency_key=idempotency_key, status="queued",
        mode="background" if request.background else "stream" if request.stream else "sync",
        model=request.model, request_payload=payload,
        response_metadata={
            "opentrace": request.opentrace.model_dump(mode="json"),
            "tenant_policy": _json_safe(tenant.get("tenant_policy") or {}),
        },
        goal_id=request.opentrace.goal_id,
    )
    db.add(record)
    await db.flush()
    input_item = ResponseItem(
        id=f"item_{uuid.uuid4().hex}", response_id=response_id, sequence_number=0,
        item_type="input_message", role="user", content=query,
        payload={"input": _json_safe(payload.get("input"))},
    )
    db.add(input_item)
    await append_event(db, response_id=response_id, event_type="response.created", payload={"response_id": response_id, "status": "queued"})
    add_outbox(db, response_id=response_id)
    session.active_response_id = response_id
    session.branch_root_response_id = session.branch_root_response_id or parent_id or response_id
    await db.commit()

    if request.stream:
        return StreamingResponse(
            _event_stream(response_id), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    if request.background:
        return _record_to_dict(record, [input_item])
    # Non-streaming clients wait on the same persisted projection. Execution
    # still belongs to an independent worker and survives this HTTP request.
    completed, items = await _wait_for_response(response_id)
    return _record_to_dict(completed, items)


@router.get("/responses/{response_id}")
async def get_response(
    response_id: str,
    http_request: Request,
    stream: bool = False,
    starting_after: int = -1,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = build_tenant_metadata(http_request, user_id=current_user.id)
    tenant_id = str(scope.get("tenant_id") or "default")
    workspace_id = str(scope.get("workspace_id") or "default")
    record = await _load_response(db, response_id, current_user, tenant_id, workspace_id)
    if stream:
        return StreamingResponse(
            _event_stream(record.id, starting_after=starting_after), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    items = (await db.execute(select(ResponseItem).where(ResponseItem.response_id == record.id).order_by(ResponseItem.sequence_number))).scalars().all()
    return _record_to_dict(record, items)


@router.get("/responses/{response_id}/events")
async def get_response_events(
    response_id: str,
    http_request: Request,
    starting_after: int = -1,
    after: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ResponseEventOut]:
    scope = build_tenant_metadata(http_request, user_id=current_user.id)
    tenant_id = str(scope.get("tenant_id") or "default")
    workspace_id = str(scope.get("workspace_id") or "default")
    await _load_response(db, response_id, current_user, tenant_id, workspace_id)
    cursor = starting_after if after is None else after
    events = (await db.execute(select(ResponseEvent).where(ResponseEvent.response_id == response_id, ResponseEvent.sequence_number > cursor).order_by(ResponseEvent.sequence_number))).scalars().all()
    return [ResponseEventOut(sequence_number=e.sequence_number, type=e.event_type, data=dict(e.payload or {}), created_at=e.created_at.isoformat() if e.created_at else "") for e in events]


@router.get("/responses/{response_id}/siblings")
async def list_response_siblings(
    response_id: str,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = build_tenant_metadata(http_request, user_id=current_user.id)
    tenant_id = str(scope.get("tenant_id") or "default")
    workspace_id = str(scope.get("workspace_id") or "default")
    source = await _load_response(db, response_id, current_user, tenant_id, workspace_id)
    session = await db.get(ChatSession, source.conversation_id)
    rows = (await db.execute(select(ResponseRecord).where(ResponseRecord.conversation_id == source.conversation_id, ResponseRecord.parent_response_id == source.parent_response_id, ResponseRecord.user_id == current_user.id).order_by(ResponseRecord.created_at))).scalars().all()
    return {"items": [{"id": row.id, "status": row.status, "created_at": row.created_at.isoformat(), "active": bool(session and session.active_response_id == row.id)} for row in rows]}


@router.post("/responses/{response_id}/retry")
async def retry_response(
    response_id: str,
    http_request: Request,
    request: ResponseRetryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = build_tenant_metadata(http_request, user_id=current_user.id)
    tenant_id = str(scope.get("tenant_id") or "default")
    workspace_id = str(scope.get("workspace_id") or "default")
    source = await _load_response(db, response_id, current_user, tenant_id, workspace_id)
    payload = dict(source.request_payload or {})
    if request.input is not None:
        payload["input"] = request.input
    payload.update({"conversation": source.conversation_id, "parent_response_id": source.parent_response_id, "previous_response_id": None, "stream": request.stream, "background": False})
    return await create_response(http_request, ResponseCreateRequest.model_validate(payload), None, current_user, db)


@router.post("/responses/{response_id}/cancel")
async def cancel_response(
    response_id: str,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = build_tenant_metadata(http_request, user_id=current_user.id)
    tenant_id = str(scope.get("tenant_id") or "default")
    workspace_id = str(scope.get("workspace_id") or "default")
    record = await _load_response(db, response_id, current_user, tenant_id, workspace_id)
    if record.status not in TERMINAL_STATUSES:
        record.status = "cancelled"
        record.completed_at = datetime.now(UTC)
        record.lease_owner = None
        record.lease_expires_at = None
        await append_event(db, response_id=response_id, event_type="response.cancelled", payload={"status": "cancelled"})
        await db.commit()
    return _record_to_dict(record)
