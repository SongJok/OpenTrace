"""Responses API compatibility surface backed by the existing CognitiveKernel.

The legacy ``/chat`` endpoint remains the execution adapter during migration.
This module owns the durable response record and a typed, replayable event
stream so clients no longer have to infer state from legacy SSE payloads.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.storage.database import AsyncSessionLocal
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import ResponseEvent, ResponseItem, ResponseRecord, User

router = APIRouter()

_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "incomplete"}


class ResponseInputItem(BaseModel):
    role: str = Field(default="user", pattern="^(user|assistant|system|tool)$")
    content: str | list[dict[str, Any]]


class ResponseCreateRequest(BaseModel):
    input: str | list[ResponseInputItem]
    conversation_id: str | None = None
    parent_response_id: str | None = None
    stream: bool = False
    background: bool = False
    web_enabled: bool = False
    graph_controls: dict[str, Any] = Field(default_factory=dict)
    enabled_skills: list[str] = Field(default_factory=list)
    disabled_skills: list[str] = Field(default_factory=list)
    tool_permission_token: str | None = None
    confirmation_granted: bool = False
    data_source_id: str | None = None
    data_source_name: str | None = None
    force_database: bool = False
    force_mode: str | None = None
    clarify_context: str | None = None
    clarify_question_id: str | None = None
    parent_message_id: str | None = None
    attachment_ids: list[str] | None = None
    reference_id: str | None = None
    reference_type: str | None = None
    state_version: int | None = None
    knowledge: dict[str, Any] = Field(default_factory=dict)
    memory_mode: str = Field(default="enabled", pattern="^(enabled|disabled|temporary)$")
    tool_choice: str = Field(default="auto", pattern="^(auto|none|required)$")


class ResponseEventOut(BaseModel):
    sequence_number: int
    type: str
    data: dict[str, Any]
    created_at: str


def extract_user_input(value: str | list[ResponseInputItem] | list[dict[str, Any]]) -> str:
    """Return the last user text while rejecting unsupported multimodal input."""
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="input 不能为空")
    for item in reversed(value):
        role = item.role if isinstance(item, ResponseInputItem) else str(item.get("role") or "")
        content = item.content if isinstance(item, ResponseInputItem) else item.get("content")
        if role != "user":
            continue
        if isinstance(content, str) and content.strip():
            return content.strip()
    raise AppException(ErrorCodes.PARAM_INVALID.code, message="input 必须包含非空 user 消息")


def translate_legacy_event(event: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Translate the legacy Kernel stream to stable semantic response events."""
    kind = str(event.get("type") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if kind == "delta":
        return [("response.output_text.delta", {"delta": str(data.get("text") or "")})]
    if kind == "final_answer":
        return [
            ("response.output_item.done", {"item_type": "message", "role": "assistant", **data}),
            ("response.completed", {"status": "completed", **data}),
        ]
    if kind == "error":
        return [("response.failed", {"status": "failed", **data})]
    if kind == "aborted":
        return [("response.cancelled", {"status": "cancelled", **data})]
    if kind == "reasoning_step":
        # This is an execution-progress summary, deliberately not a chain of thought.
        return [("response.progress", data)]
    if kind:
        return [(f"legacy.{kind}", data)]
    return []


def _record_to_dict(record: ResponseRecord, items: list[ResponseItem] | None = None) -> dict[str, Any]:
    payload = {
        "id": record.id,
        "object": "response",
        "status": record.status,
        "conversation_id": record.conversation_id,
        "parent_response_id": record.parent_response_id,
        "request_id": record.request_id,
        "mode": record.mode,
        "model": record.model,
        "error": (
            {"code": record.error_code, "message": record.error_message}
            if record.error_code or record.error_message
            else None
        ),
        "metadata": dict(record.response_metadata or {}),
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }
    if items is not None:
        payload["output"] = [
            {
                "id": item.id,
                "type": item.item_type,
                "role": item.role,
                "content": item.content,
                "payload": dict(item.payload or {}),
                "sequence_number": item.sequence_number,
            }
            for item in items
        ]
    return payload


async def _load_response(
    db: AsyncSession, response_id: str, current_user: User, tenant_id: str
) -> ResponseRecord:
    result = await db.execute(
        select(ResponseRecord).where(
            ResponseRecord.id == response_id,
            ResponseRecord.user_id == current_user.id,
            ResponseRecord.tenant_id == tenant_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Response 不存在")
    return record


async def _append_event(
    db: AsyncSession,
    *,
    response_id: str,
    sequence_number: int,
    event_type: str,
    data: dict[str, Any],
) -> None:
    db.add(
        ResponseEvent(
            id=f"evt_{uuid.uuid4().hex}",
            response_id=response_id,
            sequence_number=sequence_number,
            event_type=event_type,
            payload=data,
        )
    )


async def _persist_stream_event(
    response_id: str, sequence_number: int, event_type: str, data: dict[str, Any]
) -> bool:
    """Persist streamed output in an independent session after the request returns."""
    async with AsyncSessionLocal() as db:
        record = await db.get(ResponseRecord, response_id)
        if record is None or record.status == "cancelled":
            return False
        await _append_event(
            db,
            response_id=response_id,
            sequence_number=sequence_number,
            event_type=event_type,
            data=data,
        )
        if event_type == "response.output_item.done":
            db.add(
                ResponseItem(
                    id=f"item_{uuid.uuid4().hex}",
                    response_id=response_id,
                    sequence_number=sequence_number,
                    item_type=str(data.get("item_type") or "message"),
                    role=str(data.get("role") or "assistant"),
                    content=str(data.get("content") or ""),
                    payload=data,
                )
            )
        if event_type == "response.completed":
            record.status = "completed"
            record.completed_at = datetime.now(UTC)
            record.response_metadata = dict(data.get("metadata") or {})
        elif event_type == "response.failed":
            record.status = "failed"
            record.error_code = "legacy_stream_error"
            record.error_message = str(data.get("message") or "stream failed")
            record.completed_at = datetime.now(UTC)
        elif event_type == "response.cancelled":
            record.status = "cancelled"
            record.completed_at = datetime.now(UTC)
        await db.commit()
    return True


@router.post("/responses")
async def create_response(
    http_request: Request,
    req: ResponseCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.background:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message="background Responses 尚未启用；请使用 stream 并通过事件游标恢复。",
        )
    query = extract_user_input(req.input)
    tenant_metadata = build_tenant_metadata(http_request, user_id=current_user.id)
    tenant_id = str(tenant_metadata.get("tenant_id") or "default")
    workspace_id = str(tenant_metadata.get("workspace_id") or "default")

    if idempotency_key:
        existing = await db.execute(
            select(ResponseRecord).where(
                ResponseRecord.tenant_id == tenant_id,
                ResponseRecord.idempotency_key == idempotency_key,
            )
        )
        record = existing.scalar_one_or_none()
        if record is not None:
            if record.user_id != current_user.id:
                raise AppException(ErrorCodes.PERMISSION_DENIED.code, message="幂等键不可跨用户复用")
            items = (
                await db.execute(
                    select(ResponseItem)
                    .where(ResponseItem.response_id == record.id)
                    .order_by(ResponseItem.sequence_number)
                )
            ).scalars().all()
            return _record_to_dict(record, items)

    from gateway.api_gateway.routers import chat as legacy_chat

    conversation_id = await legacy_chat._ensure_session(
        req.conversation_id, current_user, db, tenant_metadata=tenant_metadata
    )
    response_id = f"resp_{uuid.uuid4().hex}"
    request_id = getattr(http_request.state, "request_id", "") or str(uuid.uuid4())
    record = ResponseRecord(
        id=response_id,
        conversation_id=conversation_id,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        parent_response_id=req.parent_response_id,
        request_id=request_id,
        idempotency_key=idempotency_key,
        status="in_progress",
        mode="stream" if req.stream else "sync",
        response_metadata={"memory_mode": req.memory_mode, "tool_choice": req.tool_choice},
    )
    db.add(record)
    await _append_event(
        db,
        response_id=response_id,
        sequence_number=0,
        event_type="response.created",
        data={"response_id": response_id, "status": "in_progress"},
    )
    await db.commit()

    legacy_request = legacy_chat.ChatRequest(
        query=query,
        session_id=conversation_id,
        stream=req.stream,
        memory_mode=req.memory_mode,
        web_enabled=req.web_enabled,
        request_id=request_id,
        graph_controls=req.graph_controls,
        enabled_skills=req.enabled_skills,
        disabled_skills=req.disabled_skills,
        tool_permission_token=req.tool_permission_token,
        confirmation_granted=req.confirmation_granted,
        data_source_id=req.data_source_id,
        data_source_name=req.data_source_name,
        force_database=req.force_database,
        force_mode=req.force_mode,
        clarify_context=req.clarify_context,
        clarify_question_id=req.clarify_question_id,
        parent_message_id=req.parent_message_id,
        attachment_ids=req.attachment_ids,
        reference_id=req.reference_id,
        reference_type=req.reference_type,
        state_version=req.state_version,
        knowledge=req.knowledge,
    )
    result = await legacy_chat.chat(http_request, legacy_request, current_user, db)
    if not req.stream:
        content = str(getattr(result, "content", "") or "")
        metadata = {
            "citations": list(getattr(result, "citations", []) or []),
            "evidence_refs": list(getattr(result, "evidence_refs", []) or []),
            "trace_id": getattr(result, "trace_id", None),
        }
        record.status = "completed"
        record.completed_at = datetime.now(UTC)
        record.response_metadata = metadata
        record.model = str(getattr(result, "model", "") or "") or None
        db.add(
            ResponseItem(
                id=f"item_{uuid.uuid4().hex}",
                response_id=response_id,
                sequence_number=1,
                item_type="message",
                role="assistant",
                content=content,
                payload=metadata,
            )
        )
        await _append_event(
            db,
            response_id=response_id,
            sequence_number=1,
            event_type="response.output_item.done",
            data={"item_type": "message", "role": "assistant", "content": content, **metadata},
        )
        await _append_event(
            db,
            response_id=response_id,
            sequence_number=2,
            event_type="response.completed",
            data={"status": "completed", "content": content, **metadata},
        )
        await db.commit()
        return _record_to_dict(record, [
            ResponseItem(
                id="", response_id=response_id, sequence_number=1, item_type="message",
                role="assistant", content=content, payload=metadata,
            )
        ])

    if not isinstance(result, StreamingResponse):
        raise AppException(ErrorCodes.INTERNAL_ERROR.code, message="流式适配器未返回 SSE 响应")

    async def event_stream():
        sequence_number = 1
        created = {"sequence_number": 0, "type": "response.created", "data": {"response_id": response_id, "status": "in_progress"}}
        yield f"data: {json.dumps(created, ensure_ascii=False)}\n\n"
        async for chunk in result.body_iterator:
            raw = chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
            for line in raw.splitlines():
                if not line.startswith("data:"):
                    continue
                try:
                    legacy_event = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                for event_type, data in translate_legacy_event(legacy_event):
                    if not await _persist_stream_event(response_id, sequence_number, event_type, data):
                        cancelled = {
                            "sequence_number": sequence_number,
                            "type": "response.cancelled",
                            "data": {"status": "cancelled"},
                        }
                        yield f"data: {json.dumps(cancelled, ensure_ascii=False)}\n\n"
                        return
                    event = {"sequence_number": sequence_number, "type": event_type, "data": data}
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                    sequence_number += 1

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/responses/{response_id}")
async def get_response(
    response_id: str,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = str(build_tenant_metadata(http_request, user_id=current_user.id).get("tenant_id") or "default")
    record = await _load_response(db, response_id, current_user, tenant_id)
    items = (
        await db.execute(
            select(ResponseItem)
            .where(ResponseItem.response_id == record.id)
            .order_by(ResponseItem.sequence_number)
        )
    ).scalars().all()
    return _record_to_dict(record, items)


@router.get("/responses/{response_id}/events")
async def get_response_events(
    response_id: str,
    http_request: Request,
    after: int = -1,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ResponseEventOut]:
    tenant_id = str(build_tenant_metadata(http_request, user_id=current_user.id).get("tenant_id") or "default")
    await _load_response(db, response_id, current_user, tenant_id)
    events = (
        await db.execute(
            select(ResponseEvent)
            .where(ResponseEvent.response_id == response_id, ResponseEvent.sequence_number > after)
            .order_by(ResponseEvent.sequence_number)
        )
    ).scalars().all()
    return [
        ResponseEventOut(
            sequence_number=event.sequence_number,
            type=event.event_type,
            data=dict(event.payload or {}),
            created_at=event.created_at.isoformat() if event.created_at else "",
        )
        for event in events
    ]


@router.post("/responses/{response_id}/cancel")
async def cancel_response(
    response_id: str,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = str(build_tenant_metadata(http_request, user_id=current_user.id).get("tenant_id") or "default")
    record = await _load_response(db, response_id, current_user, tenant_id)
    if record.status not in _TERMINAL_STATUSES:
        record.status = "cancelled"
        record.completed_at = datetime.now(UTC)
        latest = (
            await db.execute(
                select(ResponseEvent.sequence_number)
                .where(ResponseEvent.response_id == response_id)
                .order_by(ResponseEvent.sequence_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        await _append_event(
            db,
            response_id=response_id,
            sequence_number=(latest if latest is not None else -1) + 1,
            event_type="response.cancelled",
            data={"status": "cancelled"},
        )
        await db.commit()
    return _record_to_dict(record)
