"""Canonical, model-first Responses API surface.

The legacy ``/chat`` endpoint is a compatibility adapter only.  This router
executes a response through ``turn_coordinator`` and persists typed, replayable
events without translating a legacy chat execution stream.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import socket
import uuid
from datetime import UTC, datetime, timedelta
from enum import Enum
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.storage.database import AsyncSessionLocal
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    ChatSession,
    ResponseEvent,
    ResponseItem,
    ResponseModelCall,
    ResponseRecord,
    ResponseToolExecution,
    User,
)

router = APIRouter()

_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "incomplete"}
_ACTIVE_RESPONSE_TASKS: dict[str, asyncio.Task[Any]] = {}
_RESPONSE_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
_RESPONSE_LEASE_SECONDS = 120


def _json_safe(value: Any) -> Any:
    """Normalize runtime objects before crossing a JSON/HTTP persistence boundary.

    Cognitive runtime results intentionally contain Pydantic models (for
    example ``Evidence``), dataclasses, enums and timezone-aware datetimes.
    SQLAlchemy's JSON type and FastAPI's response encoder cannot serialize
    every one of those objects by themselves, so every durable response
    payload goes through this single provider-neutral normalizer.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
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
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


class ResponseInputItem(BaseModel):
    role: str = Field(default="user", pattern="^(user|assistant|system|developer|tool)$")
    content: str | list[dict[str, Any]]


class ResponseCreateRequest(BaseModel):
    input: str | list[ResponseInputItem]
    conversation_id: str | None = None
    previous_response_id: str | None = None
    parent_response_id: str | None = None
    model: str | None = Field(default=None, max_length=128)
    instructions: str | list[ResponseInputItem] | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    parallel_tool_calls: bool = True
    max_output_tokens: int | None = Field(default=None, ge=1, le=131072)
    truncation: str = Field(default="disabled", pattern="^(disabled|auto)$")
    store: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    text: dict[str, Any] = Field(default_factory=dict)
    reasoning: dict[str, Any] = Field(default_factory=dict)
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
    execution_profile: str = Field(default="auto", pattern="^(auto|fast|deep)$")
    execution_mode: str = Field(default="auto", pattern="^(auto|agent)$")


class ResponseEventOut(BaseModel):
    sequence_number: int
    type: str
    data: dict[str, Any]
    created_at: str


def extract_user_input(value: str | list[ResponseInputItem] | list[dict[str, Any]]) -> str:
    """Return the last user text from a typed Responses input item.

    Images and files are preserved in the request metadata for the capability
    layer.  A user turn still needs text today because the canonical kernel has
    a text query boundary; this avoids silently dropping a multimodal payload.
    """
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
        if isinstance(content, list):
            for part in reversed(content):
                if not isinstance(part, dict):
                    continue
                for key in ("text", "input_text", "content"):
                    text = part.get(key)
                    if isinstance(text, str) and text.strip():
                        return text.strip()
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


def translate_kernel_event(event: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Map canonical kernel progress to stable Response events.

    Kernel events are execution summaries, never hidden chain-of-thought.
    """
    kind = str(event.get("type") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if kind in {"delta", "answer.delta"}:
        return [("response.output_text.delta", {"delta": str(data.get("text") or "")})]
    if kind in {"reasoning_step", "task_start", "task_complete", "route.selected"}:
        return [("response.progress", {"source_type": kind, **data})]
    if kind in {"tool_call", "function_call"}:
        return [("response.output_item.added", {"item_type": "function_call", **data})]
    if kind in {"tool_result", "function_call_output"}:
        return [("response.output_item.done", {"item_type": "function_call_output", **data})]
    if kind in {"final_answer", "answer.final"}:
        content = str(data.get("content") or "")
        return [
            ("response.output_item.done", {
                "item_type": "message",
                "role": "assistant",
                "content": content,
                **data,
            }),
            ("response.completed", {"status": "completed", "content": content, **data}),
        ]
    if kind in {"error", "response.failed"}:
        return [("response.failed", {"status": "failed", **data})]
    if kind in {"aborted", "response.cancelled"}:
        return [("response.cancelled", {"status": "cancelled", **data})]
    return [("response.progress", {"source_type": kind or "unknown", **data})] if kind else []


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
        "metadata": _json_safe(dict(record.response_metadata or {})),
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
                "payload": _json_safe(dict(item.payload or {})),
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
            payload=_json_safe(data),
        )
    )


async def _persist_model_calls(
    db: AsyncSession,
    *,
    response_id: str,
    metadata: dict[str, Any],
) -> None:
    """Persist model-call provenance once the response reaches a terminal state."""
    calls = metadata.get("model_calls") if isinstance(metadata, dict) else None
    if not isinstance(calls, list):
        return
    for call in calls:
        if not isinstance(call, dict) or not call.get("id"):
            continue
        existing = await db.scalar(
            select(ResponseModelCall.id).where(
                ResponseModelCall.response_id == response_id,
                ResponseModelCall.call_id == str(call["id"]),
            )
        )
        if existing:
            continue
        db.add(
            ResponseModelCall(
                id=f"mcall_{uuid.uuid4().hex}",
                response_id=response_id,
                call_id=str(call["id"]),
                role=str(call.get("role") or "query"),
                model=str(call.get("model") or "") or None,
                latency_ms=int(call["latency_ms"]) if call.get("latency_ms") is not None else None,
                call_metadata=_json_safe({
                    key: value
                    for key, value in call.items()
                    if key not in {"id", "role", "model", "latency_ms"}
                }),
            )
        )


async def _persist_tool_log(
    db: AsyncSession,
    *,
    response_id: str,
    tool_log: list[dict[str, Any]] | None,
    start_sequence: int,
) -> int:
    """Persist provider-neutral tool calls/results for sync and background turns."""
    sequence = start_sequence
    for call in tool_log or []:
        if not isinstance(call, dict):
            continue
        call_id = str(call.get("call_id") or call.get("id") or f"call_{uuid.uuid4().hex}")
        existing = await db.scalar(
            select(ResponseToolExecution.id).where(
                ResponseToolExecution.response_id == response_id,
                ResponseToolExecution.call_id == call_id,
            )
        )
        if existing:
            continue
        tool_name = str(call.get("tool_name") or call.get("name") or "unknown")
        result_payload = call.get("result") if isinstance(call.get("result"), dict) else call.get("output")
        result_payload = result_payload if isinstance(result_payload, dict) else {"value": result_payload}
        status = str(call.get("status") or "completed")
        db.add(
            ResponseToolExecution(
                id=f"tool_{uuid.uuid4().hex}",
                response_id=response_id,
                call_id=call_id,
                idempotency_key=f"{response_id}:{call_id}",
                tool_name=tool_name,
                status=status,
                arguments=_json_safe(dict(call.get("parameters") or call.get("arguments") or {})),
                result=_json_safe(result_payload),
                error_message=str(call.get("error")) if call.get("error") else None,
                side_effect=bool(call.get("side_effect", False)),
                completed_at=datetime.now(UTC) if status in {"completed", "failed"} else None,
            )
        )
        db.add(
            ResponseItem(
                id=f"item_{uuid.uuid4().hex}",
                response_id=response_id,
                sequence_number=sequence,
                item_type="function_call_output",
                role="tool",
                content=json.dumps(result_payload, ensure_ascii=False, default=str),
                payload=_json_safe({"call_id": call_id, "name": tool_name, **call}),
            )
        )
        sequence += 1
    return sequence


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
                    payload=_json_safe(data),
                )
            )
            if str(data.get("item_type") or "") in {"function_call", "function_call_output"}:
                call_id = str(data.get("call_id") or data.get("id") or f"seq_{sequence_number}")
                tool_row = await db.scalar(
                    select(ResponseToolExecution).where(
                        ResponseToolExecution.response_id == response_id,
                        ResponseToolExecution.call_id == call_id,
                    )
                )
                if tool_row is None:
                    tool_row = ResponseToolExecution(
                        id=f"tool_{uuid.uuid4().hex}",
                        response_id=response_id,
                        call_id=call_id,
                        idempotency_key=f"{response_id}:{call_id}",
                        tool_name=str(data.get("name") or data.get("tool_name") or "unknown"),
                        status="completed" if str(data.get("item_type")) == "function_call_output" else "pending",
                        arguments=_json_safe(dict(data.get("arguments") or {})) if isinstance(data.get("arguments"), dict) else {},
                        result=_json_safe(dict(data.get("output") or {})) if isinstance(data.get("output"), dict) else {},
                        side_effect=bool(data.get("side_effect", False)),
                        completed_at=datetime.now(UTC) if str(data.get("item_type")) == "function_call_output" else None,
                    )
                    db.add(tool_row)
                elif str(data.get("item_type")) == "function_call_output":
                    tool_row.status = "completed"
                    tool_row.result = _json_safe(dict(data.get("output") or {})) if isinstance(data.get("output"), dict) else {}
                    tool_row.completed_at = datetime.now(UTC)
        if event_type == "response.completed":
            record.status = "completed"
            record.completed_at = datetime.now(UTC)
            record.response_metadata = _json_safe(dict(data.get("metadata") or {}))
            await _persist_model_calls(
                db,
                response_id=response_id,
                metadata=record.response_metadata,
            )
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


async def _next_event_sequence(db: AsyncSession, response_id: str) -> int:
    latest = (
        await db.execute(
            select(ResponseEvent.sequence_number)
            .where(ResponseEvent.response_id == response_id)
            .order_by(ResponseEvent.sequence_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return (latest if latest is not None else -1) + 1


async def _claim_background_response(
    db: AsyncSession, response_id: str, *, owner: str = _RESPONSE_WORKER_ID
) -> ResponseRecord | None:
    """Atomically claim a queued or expired Response job for one worker."""
    now = datetime.now(UTC)
    record = await db.scalar(
        select(ResponseRecord)
        .where(
            ResponseRecord.id == response_id,
            ResponseRecord.mode == "background",
            or_(
                ResponseRecord.status == "queued",
                and_(
                    ResponseRecord.status == "in_progress",
                    ResponseRecord.lease_expires_at.is_not(None),
                    ResponseRecord.lease_expires_at < now,
                ),
            ),
            ResponseRecord.attempt_count < ResponseRecord.max_attempts,
        )
        .with_for_update(skip_locked=True)
    )
    if record is None:
        return None
    record.status = "in_progress"
    record.lease_owner = owner
    record.lease_expires_at = now.replace(microsecond=0) + timedelta(seconds=_RESPONSE_LEASE_SECONDS)
    record.heartbeat_at = now
    record.attempt_count = int(record.attempt_count or 0) + 1
    await db.flush()
    return record


async def _renew_background_lease(response_id: str, owner: str) -> None:
    while True:
        await asyncio.sleep(_RESPONSE_LEASE_SECONDS / 3)
        async with AsyncSessionLocal() as db:
            record = await db.get(ResponseRecord, response_id)
            if record is None or record.status != "in_progress" or record.lease_owner != owner:
                return
            now = datetime.now(UTC)
            record.heartbeat_at = now
            record.lease_expires_at = now + timedelta(seconds=_RESPONSE_LEASE_SECONDS)
            await db.commit()


async def _run_background_response(response_id: str, prepared: Any, *, lease_owner: str = _RESPONSE_WORKER_ID) -> None:
    """Execute a durable background response and persist the same typed events."""
    from gateway.api_gateway.turn_coordinator import (
        ModelAnswerRequiredError,
        execute_prepared_turn,
    )

    try:
        async with AsyncSessionLocal() as db:
            record = await db.get(ResponseRecord, response_id)
            if record is None or record.status == "cancelled" or record.lease_owner != lease_owner:
                return
            await db.commit()
        heartbeat = asyncio.create_task(_renew_background_lease(response_id, lease_owner))
        result = await execute_prepared_turn(prepared)
        content = str(result.content or "")
        metadata = {
            **dict(result.metadata or {}),
            "citations": list((result.metadata or {}).get("citations", []) or []),
            "evidence_refs": list((result.metadata or {}).get("evidence_refs", []) or []),
            "model_required": not bool((result.metadata or {}).get("knowledge_operation")),
        }
        async with AsyncSessionLocal() as db:
            record = await db.get(ResponseRecord, response_id)
            if record is None or record.status == "cancelled" or record.lease_owner != lease_owner:
                return
            record.status = "completed"
            record.completed_at = datetime.now(UTC)
            metadata = _json_safe(metadata)
            record.response_metadata = metadata
            record.model = str(result.model or "") or None
            record.lease_owner = None
            record.lease_expires_at = None
            record.heartbeat_at = None
            next_sequence = await _persist_tool_log(
                db,
                response_id=response_id,
                tool_log=list(metadata.get("tool_calls") or []),
                start_sequence=1,
            )
            db.add(
                ResponseItem(
                    id=f"item_{uuid.uuid4().hex}",
                    response_id=response_id,
                    sequence_number=next_sequence,
                    item_type="message",
                    role="assistant",
                    content=content,
                    payload=_json_safe(metadata),
                )
            )
            seq = await _next_event_sequence(db, response_id)
            await _append_event(
                db,
                response_id=response_id,
                sequence_number=seq,
                event_type="response.output_item.done",
                data={"item_type": "message", "role": "assistant", "content": content, **metadata},
            )
            await _append_event(
                db,
                response_id=response_id,
                sequence_number=seq + 1,
                event_type="response.completed",
                data={"status": "completed", "content": content, **metadata},
            )
            await _persist_model_calls(db, response_id=response_id, metadata=metadata)
            await db.commit()
    except ModelAnswerRequiredError as exc:
        async with AsyncSessionLocal() as db:
            record = await db.get(ResponseRecord, response_id)
            if record is not None and record.status not in _TERMINAL_STATUSES:
                record.status = "failed"
                record.error_code = "primary_model_required"
                record.error_message = str(exc)
                record.completed_at = datetime.now(UTC)
                record.lease_owner = None
                record.lease_expires_at = None
                record.heartbeat_at = None
                await _append_event(
                    db,
                    response_id=response_id,
                    sequence_number=await _next_event_sequence(db, response_id),
                    event_type="response.failed",
                    data={"status": "failed", "code": record.error_code},
                )
                await db.commit()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        async with AsyncSessionLocal() as db:
            record = await db.get(ResponseRecord, response_id)
            if record is not None and record.status not in _TERMINAL_STATUSES:
                error_text = str(exc).lower()
                provider_auth_or_quota = any(
                    marker in error_text
                    for marker in ("quota", "allocationquota", "free tier", "api key", "unauthorized", "403")
                )
                if not provider_auth_or_quota and int(record.attempt_count or 0) < int(record.max_attempts or 3):
                    record.status = "queued"
                    record.error_code = "response_retry_scheduled"
                    record.error_message = str(exc)[:500]
                else:
                    record.status = "failed"
                    record.error_code = "model_unavailable" if provider_auth_or_quota else "response_execution_failed"
                    record.error_message = (
                        "模型服务暂时不可用，请检查 API Key、模型配额或稍后重试。"
                        if provider_auth_or_quota
                        else "response execution failed"
                    )
                    record.completed_at = datetime.now(UTC)
                record.lease_owner = None
                record.lease_expires_at = None
                record.heartbeat_at = None
                await _append_event(
                    db,
                    response_id=response_id,
                    sequence_number=await _next_event_sequence(db, response_id),
                    event_type="response.retrying" if record.status == "queued" else "response.failed",
                    data={"status": "failed", "code": record.error_code},
                )
                await db.commit()
    finally:
        task = locals().get("heartbeat")
        if isinstance(task, asyncio.Task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        _ACTIVE_RESPONSE_TASKS.pop(response_id, None)


async def recover_queued_background_responses(*, limit: int = 50) -> int:
    """Resume background work that was accepted before an API restart.

    Claim queued records and expired in-progress records using the same lease
    path used by a dedicated worker.  The request snapshot makes recovery
    independent from the API process that accepted the request.
    """
    from gateway.api_gateway.turn_coordinator import prepare_response_turn

    recovered = 0
    async with AsyncSessionLocal() as db:
        records = (
            await db.execute(
                select(ResponseRecord)
                .where(
                    ResponseRecord.mode == "background",
                    or_(ResponseRecord.status == "queued", ResponseRecord.status == "in_progress"),
                )
                .order_by(ResponseRecord.created_at)
                .limit(limit)
            )
        ).scalars().all()
        for record in records:
            if record.id in _ACTIVE_RESPONSE_TASKS:
                continue
            claimed = await _claim_background_response(db, record.id)
            if claimed is None:
                continue
            payload = dict(record.request_payload or {}) or dict(record.response_metadata or {}).get("request_payload")
            user = await db.get(User, record.user_id)
            if not isinstance(payload, dict) or user is None:
                record.status = "failed"
                record.error_code = "background_recovery_payload_missing"
                record.error_message = "background request cannot be reconstructed"
                record.completed_at = datetime.now(UTC)
                continue
            try:
                req = ResponseCreateRequest.model_validate(payload)
                req.background = True
                req.stream = False
                req.conversation_id = record.conversation_id
                prepared = await prepare_response_turn(
                    db=db,
                    user=user,
                    tenant_metadata={
                        "tenant_id": record.tenant_id,
                        "workspace_id": record.workspace_id,
                    },
                    query=extract_user_input(req.input),
                    request=req,
                    request_id=record.request_id,
                )
                _ACTIVE_RESPONSE_TASKS[record.id] = asyncio.create_task(
                    _run_background_response(record.id, prepared, lease_owner=_RESPONSE_WORKER_ID), name=f"response:{record.id}"
                )
                recovered += 1
            except Exception:
                record.status = "failed"
                record.error_code = "background_recovery_failed"
                record.error_message = "background request recovery failed"
                record.completed_at = datetime.now(UTC)
                record.lease_owner = None
                record.lease_expires_at = None
                record.heartbeat_at = None
        await db.commit()
    return recovered


@router.post("/responses")
async def create_response(
    http_request: Request,
    req: ResponseCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.background and not req.store:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="background 模式必须启用 store")
    query = extract_user_input(req.input)
    tenant_metadata = build_tenant_metadata(http_request, user_id=current_user.id)
    tenant_id = str(tenant_metadata.get("tenant_id") or "default")
    workspace_id = str(tenant_metadata.get("workspace_id") or "default")

    if req.conversation_id:
        existing_session = await db.scalar(select(ChatSession).where(ChatSession.id == req.conversation_id, ChatSession.user_id == current_user.id))
        if existing_session and existing_session.is_temporary:
            req.memory_mode = "temporary"

    parent_response_id = req.previous_response_id or req.parent_response_id
    if parent_response_id:
        parent = await _load_response(db, parent_response_id, current_user, tenant_id)
        if req.conversation_id and req.conversation_id != parent.conversation_id:
            raise AppException(ErrorCodes.PARAM_INVALID.code, message="conversation_id 与 previous_response_id 不一致")
        req.conversation_id = parent.conversation_id
    elif req.conversation_id:
        # The browser client normally sends only a conversation id.  Continue
        # from its active response automatically so multi-turn context survives
        # a refresh and so future retries can form a proper response tree.
        session = await db.scalar(
            select(ChatSession).where(
                ChatSession.id == req.conversation_id,
                ChatSession.user_id == current_user.id,
                ChatSession.tenant_id == tenant_id,
                ChatSession.workspace_id == workspace_id,
            )
        )
        if session is not None and session.active_response_id:
            parent = await _load_response(db, str(session.active_response_id), current_user, tenant_id)
            parent_response_id = parent.id

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

    from gateway.api_gateway.turn_coordinator import prepare_response_turn

    request_id = getattr(http_request.state, "request_id", "") or str(uuid.uuid4())
    prepared = await prepare_response_turn(
        db=db,
        user=current_user,
        tenant_metadata=tenant_metadata,
        query=query,
        request=req,
        request_id=request_id,
    )
    conversation_id = prepared.conversation_id
    response_id = f"resp_{uuid.uuid4().hex}"
    record = ResponseRecord(
        id=response_id,
        conversation_id=conversation_id,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        parent_response_id=parent_response_id,
        request_id=request_id,
        idempotency_key=idempotency_key,
        status="queued" if req.background else "in_progress",
        mode="background" if req.background else "stream" if req.stream else "sync",
        response_metadata={
            "memory_mode": req.memory_mode,
            "tool_choice": req.tool_choice,
            "model": req.model,
            "parallel_tool_calls": req.parallel_tool_calls,
            "max_output_tokens": req.max_output_tokens,
            "truncation": req.truncation,
            "store": req.store,
            "metadata": req.metadata,
            "text": req.text,
            "reasoning": req.reasoning,
            "execution_profile": req.execution_profile,
            "execution_mode": req.execution_mode,
            "request_payload": req.model_dump(mode="json"),
        },
        request_payload=req.model_dump(mode="json"),
        max_attempts=3,
    )
    db.add(record)
    session = await db.get(ChatSession, conversation_id)
    if session is not None:
        session.active_response_id = response_id
        session.branch_root_response_id = session.branch_root_response_id or parent_response_id or response_id
    # ResponseEvent/ResponseItem reference the new response row.  These
    # models intentionally use explicit foreign keys without ORM
    # relationships, so SQLAlchemy's unit-of-work cannot infer the parent
    # ordering on PostgreSQL.  Flush the parent before adding children to
    # avoid a response_events_response_id_fkey violation.
    await db.flush()
    db.add(
        ResponseItem(
            id=f"item_{uuid.uuid4().hex}",
            response_id=response_id,
            sequence_number=0,
            item_type="input_message",
            role="user",
            content=query,
            payload={
                "model_required": True,
                "input": _json_safe(
                    req.input
                    if isinstance(req.input, str)
                    else [item.model_dump(mode="json") for item in req.input]
                ),
            },
        )
    )
    await _append_event(
        db,
        response_id=response_id,
        sequence_number=0,
        event_type="response.created",
        data={"response_id": response_id, "status": "queued" if req.background else "in_progress"},
    )
    await db.commit()

    if req.background:
        async def _start_background() -> None:
            async with AsyncSessionLocal() as claim_db:
                claimed = await _claim_background_response(claim_db, response_id)
                if claimed is None:
                    return
                await claim_db.commit()
                owner = claimed.lease_owner or _RESPONSE_WORKER_ID
            _ACTIVE_RESPONSE_TASKS[response_id] = asyncio.current_task()  # type: ignore[assignment]
            await _run_background_response(response_id, prepared, lease_owner=owner)

        _ACTIVE_RESPONSE_TASKS[response_id] = asyncio.create_task(_start_background(), name=f"response:{response_id}")
        if req.stream:
            async def background_stream():
                cursor = -1
                while True:
                    async with AsyncSessionLocal() as stream_db:
                        stream_record = await stream_db.get(ResponseRecord, response_id)
                        events = (
                            await stream_db.execute(
                                select(ResponseEvent)
                                .where(ResponseEvent.response_id == response_id, ResponseEvent.sequence_number > cursor)
                                .order_by(ResponseEvent.sequence_number)
                            )
                        ).scalars().all()
                        for event in events:
                            cursor = event.sequence_number
                            yield f"data: {json.dumps({'sequence_number': cursor, 'type': event.event_type, 'data': dict(event.payload or {})}, ensure_ascii=False, default=str)}\n\n"
                        if stream_record is None or stream_record.status in _TERMINAL_STATUSES:
                            return
                    await asyncio.sleep(0.25)
            return StreamingResponse(background_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        return _record_to_dict(record, [])

    if not req.stream:
        from gateway.api_gateway.turn_coordinator import (
            ModelAnswerRequiredError,
            execute_prepared_turn,
        )

        try:
            result = await execute_prepared_turn(prepared)
        except ModelAnswerRequiredError as exc:
            record.status = "failed"
            record.error_code = "primary_model_required"
            record.error_message = str(exc)
            record.completed_at = datetime.now(UTC)
            await _append_event(
                db,
                response_id=response_id,
                sequence_number=1,
                event_type="response.failed",
                data={"status": "failed", "code": record.error_code},
            )
            await db.commit()
            return _record_to_dict(record, [])
        except Exception as exc:  # noqa: BLE001
            # Provider failures (quota, auth, upstream outage) must become a
            # durable failed Response rather than an opaque HTTP 500.  This
            # keeps the client on the Responses contract and lets it render a
            # retry affordance with the persisted response id.
            message = str(exc).lower()
            model_unavailable = any(
                marker in message
                for marker in ("quota", "allocationquota", "free tier", "api key", "unauthorized", "403")
            )
            record.status = "failed"
            record.error_code = "model_unavailable" if model_unavailable else "response_execution_failed"
            record.error_message = (
                "模型服务暂时不可用，请检查 API Key、模型配额或稍后重试。"
                if model_unavailable
                else "响应执行失败，请稍后重试。"
            )
            record.completed_at = datetime.now(UTC)
            await _append_event(
                db,
                response_id=response_id,
                sequence_number=await _next_event_sequence(db, response_id),
                event_type="response.failed",
                data={"status": "failed", "code": record.error_code, "message": record.error_message},
            )
            await db.commit()
            return _record_to_dict(record, [])
        content = str(result.content or "")
        metadata = {
            **dict(result.metadata or {}),
            "citations": list((result.metadata or {}).get("citations", []) or []),
            "evidence_refs": list((result.metadata or {}).get("evidence_refs", []) or []),
            "model_required": not bool((result.metadata or {}).get("knowledge_operation")),
        }
        record.status = "completed"
        record.completed_at = datetime.now(UTC)
        metadata = _json_safe(metadata)
        record.response_metadata = metadata
        record.model = str(result.model or "") or None
        next_sequence = await _persist_tool_log(
            db,
            response_id=response_id,
            tool_log=list(metadata.get("tool_calls") or []),
            start_sequence=1,
        )
        db.add(
            ResponseItem(
                id=f"item_{uuid.uuid4().hex}",
                response_id=response_id,
                sequence_number=next_sequence,
                item_type="message",
                role="assistant",
                content=content,
                payload=_json_safe(metadata),
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
        await _persist_model_calls(db, response_id=response_id, metadata=metadata)
        await db.commit()
        return _record_to_dict(record, [
            ResponseItem(
                id="", response_id=response_id, sequence_number=next_sequence, item_type="message",
                role="assistant", content=content, payload=_json_safe(metadata),
            )
        ])

    async def event_stream():
        from gateway.api_gateway.turn_coordinator import stream_prepared_turn

        sequence_number = 1
        created = {"sequence_number": 0, "type": "response.created", "data": {"response_id": response_id, "status": "in_progress"}}
        yield f"data: {json.dumps(created, ensure_ascii=False)}\n\n"
        try:
            async for kernel_event in stream_prepared_turn(prepared):
                for event_type, data in translate_kernel_event(kernel_event):
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
        except asyncio.CancelledError:
            # A browser tab, mobile client, or proxy may close the SSE socket
            # after receiving a prefix.  Persist that lifecycle transition so
            # the response is replayable and never remains in_progress
            # forever.  Shield the short DB write from the cancellation that
            # interrupted the stream, then re-raise for ASGI cleanup.
            try:
                await asyncio.shield(
                    _persist_stream_event(
                        response_id,
                        sequence_number,
                        "response.cancelled",
                        {"status": "cancelled", "reason": "client_disconnected"},
                    )
                )
            finally:
                raise
        except Exception:
            data = {"status": "failed", "message": "response execution failed"}
            await _persist_stream_event(response_id, sequence_number, "response.failed", data)
            event = {"sequence_number": sequence_number, "type": "response.failed", "data": data}
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/responses/{response_id}")
async def get_response(
    response_id: str,
    http_request: Request,
    stream: bool = False,
    starting_after: int = -1,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = str(build_tenant_metadata(http_request, user_id=current_user.id).get("tenant_id") or "default")
    record = await _load_response(db, response_id, current_user, tenant_id)
    if stream:
        async def resume_stream():
            cursor = starting_after
            while True:
                async with AsyncSessionLocal() as stream_db:
                    stream_record = await _load_response(stream_db, response_id, current_user, tenant_id)
                    events = (
                        await stream_db.execute(
                            select(ResponseEvent)
                            .where(ResponseEvent.response_id == response_id, ResponseEvent.sequence_number > cursor)
                            .order_by(ResponseEvent.sequence_number)
                        )
                    ).scalars().all()
                    for event in events:
                        cursor = event.sequence_number
                        yield f"data: {json.dumps({'sequence_number': cursor, 'type': event.event_type, 'data': dict(event.payload or {})}, ensure_ascii=False, default=str)}\n\n"
                    if stream_record.status in _TERMINAL_STATUSES:
                        return
                await asyncio.sleep(0.25)
        return StreamingResponse(resume_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

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


class ResponseRetryRequest(BaseModel):
    input: str | list[ResponseInputItem] | None = None
    stream: bool = True


@router.get("/responses/{response_id}/siblings")
async def list_response_siblings(
    response_id: str,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = str(build_tenant_metadata(http_request, user_id=current_user.id).get("tenant_id") or "default")
    record = await _load_response(db, response_id, current_user, tenant_id)
    session = await db.get(ChatSession, record.conversation_id)
    rows = (await db.execute(select(ResponseRecord).where(ResponseRecord.conversation_id == record.conversation_id, ResponseRecord.parent_response_id == record.parent_response_id, ResponseRecord.user_id == current_user.id).order_by(ResponseRecord.created_at))).scalars().all()
    return {"items": [{"id": r.id, "status": r.status, "created_at": r.created_at.isoformat(), "active": bool(session and r.id == session.active_response_id)} for r in rows]}


@router.post("/responses/{response_id}/retry")
async def retry_response(
    response_id: str,
    http_request: Request,
    req: ResponseRetryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = str(build_tenant_metadata(http_request, user_id=current_user.id).get("tenant_id") or "default")
    source = await _load_response(db, response_id, current_user, tenant_id)
    payload = dict(source.request_payload or {})
    if req.input is not None:
        payload["input"] = req.input
    elif not payload.get("input"):
        item = await db.scalar(select(ResponseItem).where(ResponseItem.response_id == source.id, ResponseItem.item_type == "input_message").order_by(ResponseItem.sequence_number))
        payload["input"] = item.content if item else None
    payload.update({"conversation_id": source.conversation_id, "parent_response_id": source.parent_response_id, "previous_response_id": None, "stream": req.stream, "background": False})
    return await create_response(http_request, ResponseCreateRequest.model_validate(payload), None, current_user, db)


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
        task = _ACTIVE_RESPONSE_TASKS.pop(response_id, None)
        if task is not None:
            task.cancel()
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
