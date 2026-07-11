"""
对话路由 — 经 CognitiveKernel 提供 SSE 流式与同步对话。
所有请求经认知内核（唯一中枢）；禁止直连 LLM，仅允许 Kernel.run() / Kernel.stream()。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from execution.data.query_intents import is_database_question
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.resource_scope import owned_data_sources_statement
from gateway.api_gateway.tier0_paths import (
    is_sql_retrieval_intent as _tier0_is_sql_retrieval_intent,
    sse_database_direct_events,
    sse_sql_retrieval_events,
    stream_tier0_events,
)
from kernel.runtime_gateway import Tier0ChatContext, get_runtime_gateway
from infra.audit.logger import write_audit_log
from infra.cache.redis_client import get_cache_redis
from infra.config.settings import settings
from infra.errors import AppException, ErrorCodes
from infra.guards.kernel_guard import require_kernel_entrypoint
from infra.message_bus.cognitive_event_bus import cognitive_event_bus
from infra.observability.logger import get_logger
from infra.observability.request_context import get_log_context, set_user_session_context
from infra.security.zero_trust import (
    assess_query_risk,
    issue_permission_token,
    tool_anomaly_detector,
    validate_permission_token,
)
from infra.storage.database import AsyncSessionLocal
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    Attachment,
    ChatSession,
    DataSource,
    DataSourceSchema,
    Feedback,
    Message,
    ReasoningTrace,
    ToolStat,
    TraceLog,
    User,
    UserCustomInstruction,
    UserMemory,
    UserMemorySettings,
)
from kernel.protocol.events import SpanStage, trace_context_for_request
from kernel.runtime.context import RuntimeContext
from services.file_parser import parse_attachment_content

logger = get_logger(__name__)
router = APIRouter()

_ACTIVE_STREAM_TASKS: dict[str, asyncio.Task] = {}
_ACTIVE_STREAM_CONTEXTS: dict[str, dict[str, Any]] = {}


def _public_stream_error(exc: Exception) -> str:
    if settings.debug and settings.app_env == "development":
        return str(exc)
    return "请求处理失败，请稍后重试。"


def _sanitize_assistant_output(text: str) -> str:
    """Apply the output safety layer before persistence or SSE delivery."""
    from safety.guardrails.guardrails import guardrails

    result = guardrails.check_output(text or "")
    return result.sanitized if result.sanitized is not None else (text or "")


class KnowledgeControl(BaseModel):
    action: str = Field(default="auto", pattern="^(auto|query|ingest|link|lint|merge|evolve|trace)$")
    scope: str = Field(default="session", pattern="^(session|workspace)$")
    attachment_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    publish_policy: str = Field(default="review", pattern="^(review|auto)$")
    resolution: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=8192)
    session_id: str | None = None
    stream: bool = False
    memory_mode: str = Field(default="enabled", pattern="^(enabled|disabled|temporary)$")
    web_enabled: bool = False
    request_id: str | None = None
    graph_controls: dict[str, Any] = Field(default_factory=dict)
    enabled_skills: list[str] = Field(default_factory=list)
    disabled_skills: list[str] = Field(default_factory=list)
    tool_permission_token: str | None = None
    confirmation_granted: bool = False
    data_source_id: str | None = None
    data_source_name: str | None = None
    force_database: bool = False
    force_mode: str | None = Field(
        default=None,
        pattern="^(rag|data_query|data_analysis|anomaly_tracking|product|rule_engine|vision)$",
    )
    # Multi-turn enhancement fields
    clarify_context: str | None = None
    clarify_question_id: str | None = None
    parent_message_id: str | None = None
    attachment_ids: list[str] | None = None
    reference_id: str | None = None
    reference_type: str | None = None
    state_version: int | None = None
    knowledge: KnowledgeControl = Field(default_factory=KnowledgeControl)


class AttachmentUploadResponse(BaseModel):
    attachment_id: str
    content_summary: str
    content_hash: str = ""
    is_duplicate: bool = False
    scope: str = "session"
    ingest_status: str = "temporary"


class AttachmentInfo(BaseModel):
    id: str
    filename: str
    file_size: int
    mime_type: str | None = None
    file_extension: str | None = None
    content_summary: str | None = None
    status: str
    message_id: str | None = None
    created_at: str
    scope: str = "session"
    ingest_status: str = "temporary"
    promoted_document_id: str | None = None


class AttachmentListResponse(BaseModel):
    session_id: str
    attachments: list[AttachmentInfo]
    total: int


class ChatResponse(BaseModel):
    session_id: str
    content: str
    decision_type: str = "direct"
    validation_score: float = 1.0
    passed_validation: bool = True
    intent_category: str = "qa"
    context_latency_ms: int = 0
    total_latency_ms: int = 0
    citations: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    annotations: list[dict[str, Any]] = Field(default_factory=list)
    execution_graph: dict[str, Any] | None = None
    result_refs: list[dict[str, Any]] = Field(default_factory=list)
    state_version: int = 1
    knowledge_operations: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float | None = None
    uncertainty: list[str] = Field(default_factory=list)
    trace_id: str | None = None


class ResumeRequest(BaseModel):
    session_id: str
    step_index: int = Field(..., ge=0)


class StopStreamRequest(BaseModel):
    session_id: str
    request_id: str | None = None


class GraphControlRequest(BaseModel):
    session_id: str
    request_id: str | None = None
    action: str = Field(..., pattern="^(prune|expand)$")
    node_id: str = Field(..., min_length=1, max_length=128)


class RegenerateRequest(BaseModel):
    session_id: str
    stream: bool = True
    web_enabled: bool = False


class EditRegenerateRequest(BaseModel):
    session_id: str
    message_id: str
    new_content: str = Field(..., min_length=1, max_length=8192)
    stream: bool = True
    web_enabled: bool = False


class ChatFeedbackRequest(BaseModel):
    session_id: str
    chunk_id: str | None = None
    message_id: str | None = None
    feedback_type: str = Field(..., pattern="^(like|dislike|none)$")
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    correction: str | None = Field(default=None, max_length=2048)


async def _load_history_before_message(
    db: AsyncSession,
    session_id: str,
    parent_message_id: str,
) -> list[dict[str, str]]:
    """Load conversation history up to but not including the parent message."""
    try:
        res = await db.execute(
            select(TraceLog)
            .where(TraceLog.session_id == session_id)
            .order_by(TraceLog.created_at.asc())
        )
        logs = res.scalars().all()
        history: list[dict[str, str]] = []
        for log in logs:
            if log.id == parent_message_id:
                break
            if log.query:
                history.append({"role": "user", "content": log.query})
            if log.response:
                history.append({"role": "assistant", "content": log.response})
        return history
    except Exception as exc:
        logger.warning("Chat API operation failed", error=str(exc))
        return []


async def _load_branch_checkpoint(
    db: AsyncSession,
    session_id: str,
    message_id: str,
) -> dict[str, Any] | None:
    """Load plan + results from a TraceLog for branching checkpoint reuse."""
    try:
        res = await db.execute(
            select(TraceLog).where(TraceLog.id == message_id, TraceLog.session_id == session_id)
        )
        log = res.scalar_one_or_none()
        if not log or not log.execution_graph_json:
            return None
        graph = json.loads(log.execution_graph_json)
        if not isinstance(graph, dict):
            return None
        return {
            "plan": graph.get("plan"),
            "agent_results": graph.get("agent_results", []),
            "message_id": message_id,
        }
    except Exception as exc:
        logger.warning("Chat API operation failed", error=str(exc))
        return None


async def _load_previous_turn_context(
    db: AsyncSession,
    session_id: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Load the previous turn's plan and agent results from TraceLog."""
    try:
        res = await db.execute(
            select(TraceLog)
            .where(TraceLog.session_id == session_id)
            .order_by(TraceLog.created_at.desc())
            .limit(1)
        )
        latest = res.scalar_one_or_none()
        if not latest or not latest.execution_graph_json:
            return None, []
        graph = json.loads(latest.execution_graph_json)
        if not isinstance(graph, dict):
            return None, []
        plan = graph.get("plan")
        agent_results = graph.get("agent_results", [])
        return plan, agent_results
    except Exception as exc:
        logger.warning("Chat API operation failed", error=str(exc))
        return None, []


async def _load_conversation_history(
    db: AsyncSession,
    session_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Load recent conversation turns from messages (preferred) or trace logs (fallback)."""
    try:
        from infra.storage.models import Message as MessageModel

        res = await db.execute(
            select(MessageModel)
            .where(MessageModel.session_id == session_id)
            .order_by(MessageModel.created_at.desc())
            .limit(limit * 2)
        )
        msg_rows = list(reversed(res.scalars().all()))
        if msg_rows:
            history: list[dict[str, Any]] = []
            for m in msg_rows:
                entry: dict[str, Any] = {"role": m.role}
                if m.content is not None:
                    entry["content"] = m.content
                if m.tool_calls:
                    entry["tool_calls"] = m.tool_calls
                if m.tool_call_id:
                    entry["tool_call_id"] = m.tool_call_id
                if m.name:
                    entry["name"] = m.name
                history.append(entry)
            return history
    except Exception as exc:
        logger.debug(
            "chat_history_message_table_fallback",
            session_id=session_id,
            error=str(exc),
        )

    # Fallback: load from trace_logs
    try:
        res = await db.execute(
            select(TraceLog)
            .where(TraceLog.session_id == session_id)
            .order_by(TraceLog.created_at.desc())
            .limit(limit)
        )
        logs = res.scalars().all()
        history: list[dict[str, Any]] = []
        for log in reversed(logs):
            if log.query:
                history.append({"role": "user", "content": log.query})
            if log.response:
                history.append({"role": "assistant", "content": log.response})
        return history
    except Exception as exc:
        logger.warning("Chat API operation failed", error=str(exc))
        return []


def _is_sql_retrieval_intent(query: str) -> bool:
    """Delegate to tier0_paths (single SSOT for SQL retrieval intent)."""
    return _tier0_is_sql_retrieval_intent(query)


def _is_sql_generation_intent(query: str) -> bool:
    """Check if user wants to *write/generate* SQL rather than *execute* a query.

    Examples: "帮我写一段SQL", "帮我写个sql", "写一个SQL查询", "帮我生成SQL"
    These should produce SQL text via LLM, not execute against a database.
    """
    q = query.strip().lower()
    # If it looks like a SQL retrieval question, it's NOT generation
    if _is_sql_retrieval_intent(query):
        return False
    sql_gen_keywords = [
        "帮我写一段sql",
        "帮我写个sql",
        "帮我写sql",
        "写一个sql",
        "写一段sql",
        "写sql",
        "生成sql",
        "生成一段sql",
        "帮我写一段 sql",
        "帮我写个 sql",
        "写一个 sql",
        "写一段 sql",
        "create a sql",
        "write a sql",
        "generate sql",
    ]
    return any(kw in q for kw in sql_gen_keywords)


async def _ensure_session(
    session_id: str | None,
    user: User,
    db: AsyncSession,
    *,
    tenant_metadata: dict[str, Any] | None = None,
) -> str:
    tm = tenant_metadata or {}
    tid = str(tm.get("tenant_id") or "default")
    oid = str(tm.get("org_id") or "default")
    wid = str(tm.get("workspace_id") or "default")
    if session_id:
        r = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id)
        )
        existing = r.scalar_one_or_none()
        if existing:
            try:
                existing.tenant_id = tid
                existing.org_id = oid
                existing.workspace_id = wid
                await db.commit()
            except Exception as exc:
                logger.warning("chat_session_tenant_update_skipped", error=str(exc))
            return session_id
    new_id = session_id or str(uuid.uuid4())
    db.add(
        ChatSession(
            id=new_id,
            user_id=user.id,
            title="New conversation",
            display_title="New conversation",
            tenant_id=tid,
            org_id=oid,
            workspace_id=wid,
        )
    )
    await db.commit()
    return new_id


async def _load_user_memory_preferences(
    db: AsyncSession, user_id: str, *, session_id: str = ""
) -> tuple[list[str], list[str], str]:
    """Return (content_list, tags_list, layered_context_block) from user preference memories.

    Uses PreferenceLayer priority: explicit > behavioral > project > session.
    """
    from kernel.preference_layers import (
        PreferenceLayer,
        build_layered_context_block,
        classify_memories,
    )

    r = await db.execute(
        select(UserMemory)
        .where(
            UserMemory.user_id == user_id,
            UserMemory.memory_type.in_(["semantic", "episodic"]),
            UserMemory.kind.in_(
                ["preference", "project_fact", "session_fact", "fact"]
            ),
            UserMemory.enabled.is_(True),
        )
        .order_by(UserMemory.pinned.desc(), UserMemory.score.desc(), UserMemory.updated_at.desc())
        .limit(30)
    )
    rows = r.scalars().all()
    layered = classify_memories(rows, session_id=session_id)

    contents = [lm.content for lm in layered if lm.layer == PreferenceLayer.EXPLICIT]
    tags: list[str] = []
    for lm in layered:
        tags.extend(lm.tags)

    # Build structured context block from all layers
    context_block = build_layered_context_block(layered)
    return contents, tags, context_block


async def _load_custom_instruction_block(
    db: AsyncSession,
    user_id: str,
    tenant_metadata: dict[str, Any] | None = None,
) -> str:
    """Load explicit user instructions for the current tenant/workspace scope.

    Custom instructions are intentionally independent from learned memory: they
    remain active for temporary chats, while memory reads/writes can be disabled.
    """
    from gateway.api_gateway.resource_scope import normalized_tenant_scope

    tenant_id, workspace_id = normalized_tenant_scope(tenant_metadata or {})
    row = (
        await db.execute(
            select(UserCustomInstruction).where(
                UserCustomInstruction.user_id == user_id,
                UserCustomInstruction.tenant_id == tenant_id,
                UserCustomInstruction.workspace_id == workspace_id,
                UserCustomInstruction.enabled.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return ""

    parts: list[str] = []
    about_user = (row.about_user or "").strip()
    response_style = (row.response_style or "").strip()
    if about_user:
        parts.append(f"用户明确提供的背景信息：\n{about_user[:4000]}")
    if response_style:
        parts.append(f"用户明确要求的回答风格：\n{response_style[:4000]}")
    return "\n\n".join(parts)


def _database_intent(query: str) -> bool:
    return is_database_question(query)


async def _load_data_source_context(
    db: AsyncSession,
    current_user: User,
    data_source_id: str | None,
    query: str | None = None,
    force_database: bool = False,
    tenant_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = None
    if data_source_id:
        r = await db.execute(
            owned_data_sources_statement(
                user_id=current_user.id,
                tenant_metadata=tenant_metadata,
                data_source_id=data_source_id,
            )
        )
        source = r.scalar_one_or_none()
        if source is None:
            raise AppException(ErrorCodes.PARAM_INVALID.code, message="data source not found")
    elif query:
        q = query.strip().lower()
        if q:
            r = await db.execute(
                owned_data_sources_statement(
                    user_id=current_user.id,
                    tenant_metadata=tenant_metadata,
                ).order_by(DataSource.created_at.desc())
            )
            candidates = r.scalars().all()
            for item in candidates:
                name = str(item.name or "").lower()
                database = str(item.database or "").lower()
                if name and name in q:
                    source = item
                    break
                if database and database in q:
                    source = item
                    break
                if f"{database} 表" in q or f"{name} 表" in q:
                    source = item
                    break
    if source is None and force_database:
        r = await db.execute(
            owned_data_sources_statement(
                user_id=current_user.id,
                tenant_metadata=tenant_metadata,
                active_only=True,
            )
            .order_by(DataSource.updated_at.desc())
            .limit(1)
        )
        source = r.scalar_one_or_none()
    if source is None:
        return {"data_source_id": None, "data_source_name": None, "schema": None}

    rs = await db.execute(
        select(DataSourceSchema).where(DataSourceSchema.data_source_id == source.id)
    )
    schema_row = rs.scalar_one_or_none()
    schema_payload: dict[str, Any] | None = None
    if schema_row is not None:
        try:
            schema_payload = json.loads(schema_row.schema_json or "{}")
        except Exception:
            schema_payload = None

    return {
        "data_source_id": source.id,
        "data_source_name": source.name,
        "database": source.database,
        "source_type": source.source_type,
        "schema": schema_payload,
    }


async def _memory_learning_enabled(db: AsyncSession, user_id: str) -> bool:
    r = await db.execute(select(UserMemorySettings).where(UserMemorySettings.user_id == user_id))
    s = r.scalar_one_or_none()
    return True if s is None else bool(s.memory_learning_enabled)


async def _save_user_memory_from_turn(user_id: str, query: str, response: str, *, kind: str = "fact", metadata_json: str = "") -> None:
    async with AsyncSessionLocal() as db:
        memory = UserMemory(
            id=str(uuid.uuid4()),
            user_id=user_id,
            memory_type="episodic",
            kind=kind,
            title=(query[:64] + ("…" if len(query) > 64 else "")),
            content=f"Q: {query}\nA: {response}",
            enabled=True,
            pinned=False,
            metadata_json=metadata_json,
        )
        db.add(memory)
        await db.commit()


async def _save_conversation_state_async(state_manager, cs) -> None:
    """Fire-and-forget ConversationState save, never raises."""
    try:
        await state_manager.save(cs)
    except Exception as exc:
        logger.warning("Chat API operation failed", error=str(exc))


async def _save_trace(
    session_id: str,
    query: str,
    response: str,
    latency_ms: int,
    decision_type: str = "kernel",
    validation_score: float = 1.0,
    reasoning_steps: list[dict[str, Any]] | None = None,
    execution_graph: dict[str, Any] | None = None,
    parent_message_id: str | None = None,
    attachment_ids: list[str] | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    model: str = "",
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            ctx = get_log_context()
            trace_id = ctx.get("trace_id") or None
            log = TraceLog(
                id=str(uuid.uuid4()),
                session_id=session_id,
                trace_id=trace_id,
                parent_message_id=parent_message_id,
                query=query,
                response=response,
                decision_type=decision_type,
                validation_score=validation_score,
                latency_ms=latency_ms,
                reasoning_steps_json=(
                    json.dumps(reasoning_steps, ensure_ascii=False, default=str) if reasoning_steps else None
                ),
                execution_graph_json=(
                    json.dumps(execution_graph, ensure_ascii=False, default=str) if execution_graph else None
                ),
            )
            db.add(log)

            # Also write structured Message rows (new format, parallel to TraceLog)
            turn_id = log.id
            try:
                from infra.storage.models import Message as MessageModel

                db.add(
                    MessageModel(
                        id=str(uuid.uuid4()),
                        session_id=session_id,
                        turn_id=turn_id,
                        role="user",
                        content=query,
                        content_type="text",
                    )
                )
                db.add(
                    MessageModel(
                        id=str(uuid.uuid4()),
                        session_id=session_id,
                        turn_id=turn_id,
                        role="assistant",
                        content=response,
                        content_type="text",
                        model=model or None,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        latency_ms=latency_ms,
                    )
                )
            except Exception as exc:
                logger.debug(
                    "trace_message_persist_skipped",
                    session_id=session_id,
                    error=str(exc),
                )

            # Link attachments to this trace log's user message
            message_id = f"{log.id}_q"
            if attachment_ids:
                for aid in attachment_ids:
                    r = await db.execute(
                        select(Attachment).where(
                            Attachment.id == aid, Attachment.session_id == session_id
                        )
                    )
                    att = r.scalar_one_or_none()
                    if att is not None:
                        att.message_id = message_id

            # P2: persist reasoning traces
            for i, step in enumerate(reasoning_steps or []):
                if not isinstance(step, dict):
                    continue
                phase = str(step.get("phase") or step.get("stage") or "UNKNOWN")
                score_raw = step.get("score")
                try:
                    score = float(score_raw) if score_raw is not None else None
                except Exception:
                    score = None
                db.add(
                    ReasoningTrace(
                        id=str(uuid.uuid4()),
                        session_id=session_id,
                        trace_id=trace_id,
                        phase=phase,
                        content=json.dumps(step, ensure_ascii=False, default=str),
                        score=score,
                        iteration=i,
                        phase_metadata=json.dumps({"source": "chat_router"}, ensure_ascii=False),
                    )
                )

            # P2: persist tool stats from execution graph (best-effort)
            if execution_graph and isinstance(execution_graph, dict):
                nodes = execution_graph.get("nodes", [])
                if isinstance(nodes, list):
                    for n in nodes:
                        if not isinstance(n, dict):
                            continue
                        node_type = str(n.get("type") or "")
                        if "TOOL" not in node_type.upper() and not n.get("tool"):
                            continue
                        tool_name = str(n.get("tool") or n.get("name") or "tool_router")
                        status = str(n.get("status") or "").lower()
                        success = status in {"succeeded", "success", "done", "completed"}
                        latency_v = n.get("latency_ms")
                        try:
                            avg_latency_ms = float(latency_v) if latency_v is not None else 0.0
                        except Exception:
                            avg_latency_ms = 0.0
                        db.add(
                            ToolStat(
                                id=str(uuid.uuid4()),
                                tool_name=tool_name,
                                session_id=session_id,
                                success_count=1 if success else 0,
                                failure_count=0 if success else 1,
                                avg_latency_ms=avg_latency_ms,
                                last_error=None if success else "tool_execution_failed",
                            )
                        )

            r = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
            sess = r.scalar_one_or_none()
            if sess:
                if not sess.display_title and (not sess.title or sess.title == "New conversation"):
                    auto_title = query[:60] + ("\u2026" if len(query) > 60 else "")
                    sess.title = auto_title
                    sess.display_title = auto_title
                sess.turn_count = (sess.turn_count or 0) + 1
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to save trace", error=str(exc))


def _get_kernel():
    from kernel.cognitive_kernel import CognitiveKernel

    return CognitiveKernel()


async def _build_regenerate_query(db: AsyncSession, session_id: str) -> str:
    res = await db.execute(
        select(TraceLog)
        .where(TraceLog.session_id == session_id)
        .order_by(TraceLog.created_at.desc())
        .limit(1)
    )
    latest = res.scalar_one_or_none()
    if not latest or not latest.query:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="No message to regenerate")
    return latest.query


async def _build_edit_regenerate_query(
    db: AsyncSession, session_id: str, message_id: str, new_content: str
) -> str:
    if message_id.endswith("_q"):
        trace_id = message_id[:-2]
        res = await db.execute(
            select(TraceLog).where(TraceLog.id == trace_id, TraceLog.session_id == session_id)
        )
        log = res.scalar_one_or_none()
        if log is None:
            raise AppException(ErrorCodes.PARAM_INVALID.code, message="Message not found")
        log.query = new_content
        await db.commit()
        return new_content

    raise AppException(
        ErrorCodes.PARAM_INVALID.code,
        message="Only user messages can be edited",
    )


# ── Attachment upload ────────────────────────────────────────────────────────
_ALLOWED_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/tab-separated-values",
    "application/pdf",
    "application/json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/svg+xml",
}
_ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".log",
    ".rst",
    ".csv",
    ".tsv",
    ".pdf",
    ".json",
    ".jsonl",
    ".docx",
    ".xlsx",
    ".xls",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".sql",
    ".sh",
    ".bash",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".html",
    ".css",
    ".scss",
    ".less",
    ".vue",
    ".svelte",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
}
_ATTACHMENT_TTL = 43200  # 12 hours


@router.post("/chat/attachments", response_model=AttachmentUploadResponse)
async def upload_attachment(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    message_id: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttachmentUploadResponse:
    """Upload a file attachment, parse content, persist to PostgreSQL, and cache in Redis."""
    if not settings.attachment_upload_enabled:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Attachment upload is disabled")

    # Validate session ownership
    session = await db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == current_user.id
        )
    )
    if not session:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code, message="Session not found or access denied"
        )

    # Validate extension (fast-path rejection before reading file content)
    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message=f"Unsupported file type: {ext}",
        )

    # Validate file size: try file.size first, then stream-read with a cap
    max_bytes = settings.attachment_max_size_mb * 1024 * 1024
    if file.size is not None and file.size > max_bytes:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message=f"File too large (max {settings.attachment_max_size_mb}MB)",
        )

    # Stream-read into memory with a size cap
    chunks: list[bytes] = []
    total = 0
    chunk_size = 64 * 1024  # 64KB
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise AppException(
                ErrorCodes.PARAM_INVALID.code,
                message=f"File too large (max {settings.attachment_max_size_mb}MB)",
            )
        chunks.append(chunk)
    content_bytes = b"".join(chunks)

    if total == 0:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Empty file")

    # Cross-validate MIME type against extension (prevent MIME spoofing)
    content_type = (file.content_type or "").lower()
    if content_type:
        _warn_on_mime_mismatch(file.filename, ext, content_type)

    # Compute content hash for dedup
    content_hash = hashlib.sha256(content_bytes).hexdigest()

    # Check for duplicate within the same session (same file uploaded again = new attachment)
    # We only flag content-level duplicate for informational purposes, never block
    duplicate_of: str | None = None
    existing = await db.scalars(
        select(Attachment).where(
            Attachment.session_id == session_id,
            Attachment.content_hash == content_hash,
            Attachment.status == "active",
        )
    )
    existing_list = existing.all()
    if existing_list:
        duplicate_of = existing_list[0].id

    # Save to temp storage for parsing
    attachment_id = str(uuid.uuid4())
    storage_dir = settings.attachment_storage_path
    os.makedirs(storage_dir, exist_ok=True)
    file_path = os.path.join(storage_dir, f"{attachment_id}{ext}")
    with open(file_path, "wb") as f:
        f.write(content_bytes)

    # Parse content
    try:
        content = await parse_attachment_content(file_path, content_type)
    except Exception as e:
        logger.error("Attachment parsing failed", error=str(e), file_name=file.filename)
        content = f"[文件解析失败：{e}]"

    # Extract raw image data for VisionAgent (before file cleanup)
    from services.file_parser import get_image_raw_data

    raw_image = get_image_raw_data(file_path)  # (base64, mime) or None

    image_base64: str | None = None
    image_mime: str | None = None
    if raw_image:
        image_base64, image_mime = raw_image

    # Persist to PostgreSQL
    summary = content[:200] + ("..." if len(content) > 200 else "")
    content_text = content if len(content) <= 100_000 else content[:100_000]
    attachment = Attachment(
        id=attachment_id,
        session_id=session_id,
        user_id=current_user.id,
        filename=file.filename or "",
        file_size=total,
        mime_type=content_type or None,
        file_extension=ext,
        content_hash=content_hash,
        content_text=content_text,
        content_summary=summary,
        status="active",
        image_base64=image_base64,
        image_mime=image_mime,
        message_id=message_id,
        duplicate_of=duplicate_of,
    )
    db.add(attachment)
    await db.commit()

    # Update ConversationState to track this attachment (fire-and-forget)
    try:
        from kernel.conversation_state import ConversationStateManager

        state_manager = ConversationStateManager()
        cs = await state_manager.get_or_create(session_id)
        if attachment_id not in cs.active_attachment_ids:
            cs.active_attachment_ids = [*cs.active_attachment_ids, attachment_id]
            asyncio.create_task(_save_conversation_state_async(state_manager, cs))
    except Exception as state_exc:
        logger.warning("Failed to update ConversationState after upload", error=str(state_exc))

    # Cache in Redis for fast read path (TTL: 12h)
    redis = await get_cache_redis()
    redis_key = f"attachment:{attachment_id}:content"
    await redis.setex(redis_key, _ATTACHMENT_TTL, content)
    if raw_image:
        raw_key = f"attachment:{attachment_id}:raw"
        raw_data = json.dumps({"base64": image_base64, "mime": image_mime}, ensure_ascii=False)
        await redis.setex(raw_key, _ATTACHMENT_TTL, raw_data)

    # Cleanup temp file (content is in PostgreSQL + Redis)
    try:
        os.remove(file_path)
    except OSError:
        pass

    logger.info(
        "Attachment uploaded",
        attachment_id=attachment_id,
        file_name=file.filename,
        size=total,
        is_duplicate=duplicate_of is not None,
    )
    return AttachmentUploadResponse(
        attachment_id=attachment_id,
        content_summary=summary,
        content_hash=content_hash,
        is_duplicate=duplicate_of is not None,
        scope=getattr(attachment, "scope", "session"),
        ingest_status=getattr(attachment, "ingest_status", "temporary"),
    )


def _warn_on_mime_mismatch(filename: str | None, ext: str, content_type: str) -> None:
    """Log a warning if the claimed MIME type doesn't match the file extension."""
    # Broad MIME categories that are acceptable for each extension family
    _EXT_MIME_OK: dict[str, set[str]] = {
        ".txt": {"text/", "application/octet-stream"},
        ".md": {"text/", "application/octet-stream"},
        ".csv": {"text/", "application/octet-stream", "application/csv"},
        ".pdf": {"application/pdf", "application/octet-stream"},
        ".json": {"application/json", "text/", "application/octet-stream"},
        ".docx": {"application/vnd.openxmlformats-officedocument", "application/octet-stream"},
        ".xlsx": {
            "application/vnd.openxmlformats-officedocument",
            "application/vnd.ms-excel",
            "application/octet-stream",
        },
        ".png": {"image/png", "image/", "application/octet-stream"},
        ".jpg": {"image/jpeg", "image/", "application/octet-stream"},
        ".jpeg": {"image/jpeg", "image/", "application/octet-stream"},
        ".gif": {"image/gif", "image/", "application/octet-stream"},
        ".webp": {"image/webp", "image/", "application/octet-stream"},
    }
    ok_prefixes = _EXT_MIME_OK.get(ext)
    if ok_prefixes is None:
        return  # Unknown extension — already allowed by extension whitelist
    if not any(content_type.startswith(p) for p in ok_prefixes):
        logger.warning(
            "MIME type mismatch for attachment",
            filename=filename,
            extension=ext,
            claimed_mime=content_type,
        )


@router.get("/chat/attachments/{session_id}", response_model=AttachmentListResponse)
async def list_attachments(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttachmentListResponse:
    """List all active attachments for a session."""
    rows = (
        (
            await db.execute(
                select(Attachment)
                .where(
                    Attachment.session_id == session_id,
                    Attachment.user_id == current_user.id,
                    Attachment.status == "active",
                )
                .order_by(Attachment.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    return AttachmentListResponse(
        session_id=session_id,
        attachments=[
            AttachmentInfo(
                id=att.id,
                filename=att.filename,
                file_size=att.file_size,
                mime_type=att.mime_type,
                file_extension=att.file_extension,
                content_summary=att.content_summary,
                status=att.status,
                message_id=att.message_id,
                created_at=att.created_at.isoformat() if att.created_at else "",
                scope=getattr(att, "scope", "session"),
                ingest_status=getattr(att, "ingest_status", "temporary"),
                promoted_document_id=getattr(att, "promoted_document_id", None),
            )
            for att in rows
        ],
        total=len(rows),
    )


@router.post("/chat/attachments/{attachment_id}/promote", response_model=dict)
async def promote_chat_attachment(
    http_request: Request,
    attachment_id: str,
    publish_policy: str = "review",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Promote a session attachment into the governed workspace knowledge flow."""
    from gateway.api_gateway.tenant_middleware import build_tenant_metadata
    from gateway.api_gateway.resource_scope import normalized_tenant_scope
    from knowledge.chat_actions import promote_attachment_to_document

    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    if publish_policy not in {"review", "auto"}:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Invalid publish policy")
    try:
        result = await promote_attachment_to_document(
            db,
            attachment_id=attachment_id,
            user=current_user,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            publish_policy=publish_policy,
        )
        await db.commit()
        from knowledge.jobs import enqueue_document_compile

        if result.get("document_id") and result.get("status") == "queued":
            result.update(await enqueue_document_compile(result["document_id"]))
        return result
    except ValueError as exc:
        await db.rollback()
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc)) from exc


@router.delete("/chat/attachments/{attachment_id}", response_model=dict)
async def delete_attachment(
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Soft-delete an attachment by ID. Only the owner can delete their attachment."""
    att = await db.scalar(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.user_id == current_user.id,
        )
    )
    if not att:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code, message="Attachment not found or access denied"
        )

    att.status = "deleted"
    att.updated_at = datetime.utcnow()
    await db.commit()

    # Also invalidate Redis cache
    redis = await get_cache_redis()
    await redis.delete(f"attachment:{attachment_id}:content")
    await redis.delete(f"attachment:{attachment_id}:raw")

    logger.info("Attachment deleted", attachment_id=attachment_id)
    return {"attachment_id": attachment_id, "status": "deleted"}


@router.post("/chat", response_model=None)
@require_kernel_entrypoint
async def chat(
    http_request: Request,
    req: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse | StreamingResponse:
    try:
        from safety.guardrails.guardrails import guardrails

        guard = guardrails.check_input(req.query)
        if not guard.allowed:
            raise AppException(ErrorCodes.PARAM_INVALID.code, message=f"Blocked: {guard.reason}")
    except AppException:
        raise
    except Exception as exc:
        # A safety subsystem outage must not silently turn into an unrestricted
        # model call.  Fail closed and expose a stable public error.
        logger.error("Chat input safety check unavailable", error=str(exc))
        raise AppException(
            ErrorCodes.UPSTREAM_UNAVAILABLE.code,
            message="安全检查暂时不可用，请稍后重试。",
        ) from exc

    try:
        from gateway.api_gateway.tenant_middleware import build_tenant_metadata

        tenant_md = build_tenant_metadata(http_request, user_id=current_user.id)
        try:
            from gateway.api_gateway.chat_preflight import run_chat_preflight_async

            tenant_md = await run_chat_preflight_async(
                query=req.query,
                user_id=current_user.id,
                session_id=req.session_id or "",
                tenant_md=tenant_md,
            )
        except AppException:
            raise
        except Exception as exc:
            logger.warning("chat_preflight_skipped", error=str(exc))

        session_id = await _ensure_session(
            req.session_id, current_user, db, tenant_metadata=tenant_md
        )
        set_user_session_context(user_id=current_user.id, session_id=session_id)

        try:
            from tenant.tenant_isolation import set_session_tenant_context
            from tenant.tenant_context import resolve_tenant_context

            tctx = resolve_tenant_context(user_id=current_user.id, metadata=tenant_md)
            await set_session_tenant_context(db, tctx)
        except Exception as exc:
            logger.warning("chat_session_tenant_context_skipped", error=str(exc))

        # Load conversation history for multi-turn support
        conversation_history = await _load_conversation_history(db, session_id, limit=10)

        # ── Feature ⑥: Conversation Branching ────────────────────────
        branch_checkpoint: dict[str, Any] | None = None
        is_branch_request = False
        if req.parent_message_id and settings.kernel_conversation_branching_enabled:
            history_before = await _load_history_before_message(
                db, session_id, req.parent_message_id
            )
            if history_before:
                conversation_history = history_before
            branch_checkpoint = await _load_branch_checkpoint(db, session_id, req.parent_message_id)
            is_branch_request = True
        # ── End Conversation Branching ──────────────────────────────

        request_id = req.request_id or str(uuid.uuid4())
        trace_ctx = trace_context_for_request(
            request_id, session_id=session_id, user_id=current_user.id
        )
        if req.memory_mode == "enabled":
            user_preferences, _user_preference_tags, pref_context_block = await _load_user_memory_preferences(
                db, current_user.id, session_id=session_id
            )
        else:
            user_preferences, _user_preference_tags, pref_context_block = [], [], ""
        custom_instruction_block = await _load_custom_instruction_block(
            db, current_user.id, tenant_metadata=tenant_md
        )

        risk = assess_query_risk(req.query)
        required_permissions = list(risk.required_permissions)
        if required_permissions:
            if not req.tool_permission_token or not await validate_permission_token(
                session_id, req.tool_permission_token, required_permissions
            ):
                token = await issue_permission_token(session_id, required_permissions)
                await write_audit_log(
                    user_id=current_user.id,
                    action="security.permission.issued",
                    resource_type="session",
                    resource_id=session_id,
                    payload={
                        "required_permissions": required_permissions,
                        "risk_level": risk.risk_level,
                    },
                )
                raise AppException(
                    ErrorCodes.PARAM_INVALID.code,
                    message=json.dumps(
                        {
                            "requires_confirmation": risk.requires_confirmation,
                            "risk_level": risk.risk_level,
                            "reason": risk.reason,
                            "required_permissions": required_permissions,
                            "tool_permission_token": token,
                        },
                        ensure_ascii=False,
                    ),
                )
            if risk.requires_confirmation and not req.confirmation_granted:
                raise AppException(
                    ErrorCodes.PARAM_INVALID.code,
                    message=json.dumps(
                        {
                            "requires_confirmation": True,
                            "risk_level": risk.risk_level,
                            "reason": risk.reason,
                            "required_permissions": required_permissions,
                        },
                        ensure_ascii=False,
                    ),
                )
        graph_controls = {
            "pruned_nodes": list((req.graph_controls or {}).get("pruned_nodes", [])),
            "expanded_nodes": list((req.graph_controls or {}).get("expanded_nodes", [])),
        }
        data_source_context: dict[str, Any] = {
            "data_source_id": None,
            "data_source_name": None,
            "database": None,
            "source_type": None,
            "schema": None,
        }
        data_source_id = (req.data_source_id or "").strip() or None
        force_database = bool(req.force_database) or (
            _database_intent(req.query)
            and not _is_sql_generation_intent(req.query)
            and not _is_sql_retrieval_intent(req.query)
        )
        if force_database and not data_source_id:
            data_source_context = await _load_data_source_context(
                db,
                current_user,
                None,
                req.query,
                force_database=True,
                tenant_metadata=tenant_md,
            )
        elif data_source_id:
            data_source_context = await _load_data_source_context(
                db,
                current_user,
                data_source_id,
                None if data_source_id else req.query,
                tenant_metadata=tenant_md,
            )

        # Load previous turn context for multi-turn enhancement features
        prev_plan, prev_results = await _load_previous_turn_context(db, session_id)

        # Load attachment content: PostgreSQL first, fall back to Redis.
        # When no attachment_ids provided, auto-include most recent active session attachments (capped).
        _MAX_AUTO_ATTACHMENTS = 10
        _MAX_AUTO_ATTACHMENT_CONTENT_BYTES = 50_000  # 50KB total across all auto-loaded attachments
        attachment_contexts: list[dict[str, Any]] = []
        effective_attachment_ids = list(req.attachment_ids or [])
        if not effective_attachment_ids:
            # Auto-include most recent active attachments for this session (capped)
            session_attachments = (
                (
                    await db.execute(
                        select(Attachment)
                        .where(
                            Attachment.session_id == session_id,
                            Attachment.status == "active",
                        )
                        .order_by(Attachment.created_at.desc())
                        .limit(_MAX_AUTO_ATTACHMENTS)
                    )
                )
                .scalars()
                .all()
            )
            effective_attachment_ids = [att.id for att in session_attachments]
        if effective_attachment_ids:
            # Batch-load from PostgreSQL
            pg_attachments = (
                (
                    await db.execute(
                        select(Attachment).where(
                            Attachment.session_id == session_id,
                            Attachment.id.in_(effective_attachment_ids),
                            Attachment.status == "active",
                        )
                    )
                )
                .scalars()
                .all()
            )
            pg_map: dict[str, str] = {}
            for att in pg_attachments:
                if att.content_text:
                    pg_map[att.id] = att.content_text
            # Fall back to Redis for any IDs not found in PostgreSQL (backward compat)
            missing_ids = [aid for aid in effective_attachment_ids if aid not in pg_map]
            if missing_ids:
                redis = await get_cache_redis()
                for aid in missing_ids:
                    raw = await redis.get(f"attachment:{aid}:content")
                    if raw:
                        content = raw.decode() if isinstance(raw, bytes) else raw
                        pg_map[aid] = content
            # Only apply the size cap to auto-loaded attachments — explicitly
            # provided attachment_ids are always loaded in full.
            explicit_ids = bool(req.attachment_ids)
            total_content_bytes = 0
            for aid in effective_attachment_ids:
                if aid in pg_map:
                    content = pg_map[aid]
                    total_content_bytes += len(content.encode("utf-8"))
                    if (
                        not explicit_ids
                        and total_content_bytes > _MAX_AUTO_ATTACHMENT_CONTENT_BYTES
                    ):
                        break
                    attachment_contexts.append({"attachment_id": aid, "content": content})

        # ── Load ConversationState for multi-turn reference resolution ──
        from kernel.conversation_state import ConversationStateManager

        state_manager = ConversationStateManager()
        conversation_state = await state_manager.get_or_create(session_id)

        # Merge explicit attachment_ids into ConversationState so they persist across turns
        if req.attachment_ids and any(
            aid not in conversation_state.active_attachment_ids for aid in req.attachment_ids
        ):
            new_ids = [
                aid
                for aid in req.attachment_ids
                if aid not in conversation_state.active_attachment_ids
            ]
            conversation_state.active_attachment_ids = [
                *conversation_state.active_attachment_ids,
                *new_ids,
            ]
            asyncio.create_task(_save_conversation_state_async(state_manager, conversation_state))

        runtime_ctx = RuntimeContext(
            request_id=request_id,
            session_id=session_id,
            user_id=current_user.id,
            query=req.query,
            metadata=dict(tenant_md),
            conversation_history=conversation_history,
            conversation_state=conversation_state,
            user_preferences=user_preferences,
            preference_context_block=pref_context_block,
            custom_instruction_block=custom_instruction_block,
            data_source_context=data_source_context,
            attachment_contexts=attachment_contexts,
            force_mode=req.force_mode,
            web_enabled=req.web_enabled,
            graph_controls=graph_controls,
            is_branch_request=is_branch_request,
            branch_checkpoint=branch_checkpoint,
            parent_message_id=req.parent_message_id,
            previous_plan=prev_plan,
            previous_results=prev_results,
            clarify_context=req.clarify_context,
            clarify_question_id=req.clarify_question_id,
            enabled_skills=req.enabled_skills,
            disabled_skills=req.disabled_skills,
            risk_assessment={
                "risk_level": risk.risk_level,
                "reason": risk.reason,
                "requires_confirmation": risk.requires_confirmation,
            },
            tool_permission_token=req.tool_permission_token,
            memory_mode=req.memory_mode,
            stream=req.stream,
            trace_ctx=trace_ctx,
        )

        # Backward-compat KernelRequest for existing kernel code (Phase 2 will remove this)
        from kernel.cognitive_kernel import KernelRequest

        try:
            from infra.observability.turn_metering import reset_turn_tokens

            reset_turn_tokens()
        except Exception as exc:
            logger.warning("turn_metering_reset_skipped", error=str(exc))

        kernel_metadata = runtime_ctx.to_metadata_dict()
        for _tk in ("tenant_id", "org_id", "workspace_id", "data_residency"):
            if tenant_md.get(_tk) is not None:
                kernel_metadata[_tk] = tenant_md[_tk]
        kernel_metadata.setdefault("tenant_id", str(tenant_md.get("tenant_id") or "default"))
        kernel_metadata.setdefault("workspace_id", str(tenant_md.get("workspace_id") or "default"))
        kernel_metadata["history"] = list(conversation_history or [])
        kernel_metadata["knowledge_control"] = req.knowledge.model_dump()
        kernel_request = KernelRequest(
            query=req.query,
            session_id=session_id,
            user_id=current_user.id,
            history=conversation_history,
            stream=req.stream,
            web_enabled=req.web_enabled,
            trace_ctx=trace_ctx,
            conversation_state=conversation_state,
            metadata=kernel_metadata,
        )
        try:
            from kernel.turn_bootstrap import bootstrap_turn_intent

            await bootstrap_turn_intent(kernel_request)
            runtime_ctx.metadata = dict(kernel_request.metadata or {})
            if kernel_request.query != req.query:
                runtime_ctx.query = kernel_request.query
        except Exception as exc:
            logger.warning("chat_turn_bootstrap_skipped", error=str(exc))

        dispatch_query = (
            str(kernel_request.query or "").strip()
            or str(getattr(runtime_ctx, "query", "") or "").strip()
            or str(req.query or "").strip()
        )

    except AppException:
        raise
    except Exception as exc:
        logger.exception("Chat endpoint setup failed")
        return ChatResponse(
            session_id=req.session_id or "",
            content="抱歉，服务暂时不可用，请稍后重试。",
            decision_type="setup_error",
            validation_score=0.0,
            passed_validation=False,
            intent_category="error",
            context_latency_ms=0,
            total_latency_ms=0,
            citations=[],
            annotations=[],
            execution_graph={"route": "setup_error", "error": str(exc)[:200]},
        )

    t0 = time.monotonic()
    trace_id = get_log_context().get("trace_id") or request_id
    gateway_span = trace_ctx.start_span(SpanStage.GATEWAY)
    await cognitive_event_bus.publish(
        cognitive_event_bus.emit_planning(
            trace_id=trace_id,
            span_id=gateway_span,
            parent_span_id=trace_ctx.root_span_id,
            payload={
                "action": "chat.request.received",
                "query": dispatch_query,
                "raw_query": req.query,
                "session_id": session_id,
                "stream": req.stream,
                "web_enabled": req.web_enabled,
                "force_database": force_database,
                "force_mode": req.force_mode,
                "data_source_id": data_source_context.get("data_source_id"),
                "data_source_name": data_source_context.get("data_source_name"),
            },
            session_id=session_id,
            request_id=request_id,
            user_id=current_user.id,
            source="chat_router",
        )
    )

    # Explicit conversational knowledge primitives are handled before data or
    # general execution.  Ordinary knowledge questions keep flowing through
    # the single runtime router and RAG lane.
    from gateway.api_gateway.resource_scope import normalized_tenant_scope
    from knowledge.chat_actions import infer_knowledge_action, perform_knowledge_action

    knowledge_control = req.knowledge or KnowledgeControl()
    knowledge_action = knowledge_control.action
    if knowledge_action == "auto":
        knowledge_action = infer_knowledge_action(dispatch_query)
    if knowledge_action != "query":
        try:
            action_result = await perform_knowledge_action(
                db,
                action=knowledge_action,
                user=current_user,
                tenant_id=normalized_tenant_scope(tenant_md)[0],
                workspace_id=normalized_tenant_scope(tenant_md)[1],
                attachment_ids=knowledge_control.attachment_ids or effective_attachment_ids,
                source_ids=knowledge_control.source_ids,
                publish_policy=knowledge_control.publish_policy,
                resolution=knowledge_control.resolution,
            )
        except ValueError as exc:
            raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc)) from exc
        action_data = action_result.to_dict()
        action_text = action_result.message
        action_metadata = {
            "knowledge_action": action_data,
            "route": "knowledge_action",
            "trace_id": trace_id,
            "uncertainty": [],
        }
        if not req.stream:
            return ChatResponse(
                session_id=session_id,
                content=action_text,
                decision_type=f"knowledge_{knowledge_action}",
                validation_score=1.0,
                passed_validation=True,
                intent_category=f"knowledge_{knowledge_action}",
                total_latency_ms=int((time.monotonic() - t0) * 1000),
                execution_graph={"route": "knowledge_action", "action": knowledge_action},
                knowledge_operations=action_result.operations,
                confidence=1.0 if action_result.status in {"completed", "queued", "published"} else 0.5,
                trace_id=trace_id,
            )

        async def _sse_knowledge_action() -> AsyncIterator[str]:
            events = [
                {"type": "turn.accepted", "data": {"trace_id": trace_id}},
                {"type": "route.selected", "data": {"route": "knowledge_action", "action": knowledge_action}},
                {"type": "knowledge.ingest.status" if knowledge_action == "ingest" else "knowledge.operation.status", "data": action_data},
                {"type": "answer.delta", "data": {"text": action_text}},
                {"type": "answer.final", "data": {"content": action_text, **action_metadata, "knowledge_operations": action_result.operations}},
                {"type": "turn.completed", "data": {"trace_id": trace_id, "route": "knowledge_action"}},
            ]
            for event in events:
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

        return StreamingResponse(
            _sse_knowledge_action(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    from gateway.api_gateway.routers.data import DataQueryRequest, data_query

    tier0_ctx = Tier0ChatContext(
        db=db,
        current_user=current_user,
        data_query_fn=data_query,
        data_query_request_factory=DataQueryRequest,
    )
    gateway = get_runtime_gateway()
    tier0_outcome = await gateway.try_tier0_chat(
        query=dispatch_query,
        session_id=session_id,
        request_id=request_id,
        tier0_ctx=tier0_ctx,
        force_database=bool(force_database and data_source_context.get("data_source_id")),
        data_source_id=str(data_source_context.get("data_source_id") or "") or None,
    )
    sql_tier0 = tier0_outcome if tier0_outcome and tier0_outcome.decision_type == "sql_retrieval" else None
    if sql_tier0 and sql_tier0.handled:
        latency_ms = int((time.monotonic() - t0) * 1000)
        content = sql_tier0.content
        exec_graph = sql_tier0.execution_graph
        if not req.stream:
            updated_state = state_manager.apply_patch(conversation_state, sql_tier0.state_patch)
            updated_state = state_manager.advance_turn(updated_state, dispatch_query, content)
            state_manager.add_confidence(updated_state, updated_state.turn_sequence, 1.0)
            updated_state = state_manager.compact(updated_state)
            asyncio.create_task(_save_conversation_state_async(state_manager, updated_state))
            return ChatResponse(
                session_id=session_id,
                content=content,
                decision_type=sql_tier0.decision_type,
                validation_score=sql_tier0.validation_score,
                passed_validation=True,
                intent_category="sql_retrieval",
                context_latency_ms=0,
                total_latency_ms=latency_ms,
                citations=[],
                annotations=[],
                execution_graph=exec_graph,
                state_version=updated_state.state_version,
            )

        async def _sse_sql_retrieval() -> AsyncIterator[str]:
            try:
                async for event in stream_tier0_events(
                    sse_sql_retrieval_events(content, exec_graph)
                ):
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                yield ": done\n\n"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("SQL retrieval stream error", error=str(exc))
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': _public_stream_error(exc)}}, ensure_ascii=False)}\n\n"
                yield ": done\n\n"

        asyncio.create_task(
            _save_trace(
                session_id,
                dispatch_query,
                content,
                latency_ms,
                sql_tier0.decision_type,
                sql_tier0.validation_score,
                [],
                exec_graph,
                parent_message_id=req.parent_message_id,
                attachment_ids=req.attachment_ids,
            )
        )
        sql_updated = state_manager.apply_patch(conversation_state, sql_tier0.state_patch)
        sql_updated = state_manager.advance_turn(sql_updated, dispatch_query, content)
        state_manager.add_confidence(sql_updated, sql_updated.turn_sequence, 1.0)
        sql_updated = state_manager.compact(sql_updated)
        asyncio.create_task(_save_conversation_state_async(state_manager, sql_updated))
        return StreamingResponse(
            _sse_sql_retrieval(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    db_tier0 = (
        tier0_outcome
        if tier0_outcome
        and tier0_outcome.handled
        and tier0_outcome.decision_type == "database_direct"
        else None
    )
    if db_tier0 and db_tier0.handled:
        latency_ms = int((time.monotonic() - t0) * 1000)
        direct_summary = db_tier0.content
        exec_graph = db_tier0.execution_graph
        reg_agent = str(exec_graph.get("agent_type") or "data")
        if not req.stream:
            db_updated = state_manager.apply_patch(conversation_state, db_tier0.state_patch)
            db_updated = state_manager.advance_turn(db_updated, dispatch_query, direct_summary)
            state_manager.add_confidence(db_updated, db_updated.turn_sequence, 0.9)
            db_updated = state_manager.compact(db_updated)
            asyncio.create_task(_save_conversation_state_async(state_manager, db_updated))
            return ChatResponse(
                session_id=session_id,
                content=direct_summary,
                decision_type=db_tier0.decision_type,
                validation_score=db_tier0.validation_score,
                passed_validation=True,
                intent_category="data_query",
                context_latency_ms=0,
                total_latency_ms=latency_ms,
                citations=[],
                annotations=[],
                execution_graph=exec_graph,
                state_version=db_updated.state_version,
            )

        async def _sse_direct_query() -> AsyncIterator[str]:
            try:
                events = sse_database_direct_events(
                    dispatch_query, direct_summary, exec_graph, registry_agent=reg_agent
                )
                async for event in stream_tier0_events(events):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                asyncio.create_task(
                    _save_trace(
                        session_id,
                        dispatch_query,
                        direct_summary,
                        int((time.monotonic() - t0) * 1000),
                        db_tier0.decision_type,
                        db_tier0.validation_score,
                        [],
                        exec_graph,
                        parent_message_id=req.parent_message_id,
                        attachment_ids=req.attachment_ids,
                    )
                )
                _db_stream_state = state_manager.apply_patch(
                    conversation_state, db_tier0.state_patch
                )
                _db_stream_state = state_manager.advance_turn(
                    _db_stream_state, dispatch_query, direct_summary
                )
                state_manager.add_confidence(_db_stream_state, _db_stream_state.turn_sequence, 0.9)
                _db_stream_state = state_manager.compact(_db_stream_state)
                asyncio.create_task(
                    _save_conversation_state_async(state_manager, _db_stream_state)
                )
                yield ": done\n\n"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Direct query stream error", error=str(exc))
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': _public_stream_error(exc)}}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            _sse_direct_query(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if force_database and data_source_context.get("data_source_id") and not (
        tier0_outcome and tier0_outcome.handled
    ):
        logger.warning(
            "Database tier0 path failed, fallback to kernel",
            data_source_id=data_source_context.get("data_source_id"),
        )

    if req.stream:

        async def _sse() -> AsyncIterator[str]:
            final_content = ""
            final_execution_graph: dict[str, Any] | None = None
            final_reasoning_steps: list[dict[str, Any]] = []
            final_state_patch: dict[str, Any] | None = None
            final_state_persisted = False
            task_key = f"{session_id}:{request_id}"

            async def _runner() -> None:
                nonlocal final_content, final_execution_graph, final_reasoning_steps, final_state_patch, final_state_persisted
                try:
                    kernel = _get_kernel()
                    async for event in kernel.stream(kernel_request):
                        event_type = str(event.get("type") or "")
                        data = event.get("data") or {}
                        if event_type == "reasoning_step" and isinstance(data, dict):
                            final_reasoning_steps.append(data)
                            await cognitive_event_bus.publish(
                                cognitive_event_bus.emit_execution(
                                    trace_id=trace_id,
                                    span_id=trace_ctx.start_span(
                                        SpanStage.AGENT_EXECUTION, parent_span_id=gateway_span
                                    ),
                                    parent_span_id=gateway_span,
                                    payload={"action": "reasoning_step", "data": data},
                                    session_id=session_id,
                                    request_id=request_id,
                                    user_id=current_user.id,
                                    source="kernel_stream",
                                )
                            )
                        elif event_type == "final_answer" and isinstance(data, dict):
                            final_content = _sanitize_assistant_output(str(data.get("content", "")))
                            data["content"] = final_content
                            graph = data.get("execution_graph")
                            if isinstance(graph, dict):
                                final_execution_graph = graph
                            final_state_patch = data.get("state_patch")
                            if isinstance(final_state_patch, dict):
                                pass  # captured, will be persisted below
                            else:
                                final_state_patch = None
                            final_state_version = conversation_state.state_version
                            try:
                                cs = await state_manager.load(session_id)
                                if cs is None:
                                    cs = conversation_state
                                if final_state_patch is not None:
                                    state_manager.apply_patch(cs, final_state_patch)
                                state_manager.advance_turn(cs, dispatch_query, final_content)
                                score = data.get("validation_score", 0.85)
                                try:
                                    confidence = float(score)
                                except (TypeError, ValueError):
                                    confidence = 0.85
                                state_manager.add_confidence(
                                    cs,
                                    cs.turn_sequence,
                                    confidence,
                                    components={"route": str(data.get("route") or "kernel_stream")},
                                )
                                state_manager.compact(cs)
                                await state_manager.save(cs)
                                final_state_version = cs.state_version
                                final_state_persisted = True
                            except Exception as state_exc:
                                logger.warning(
                                    "Failed to persist ConversationState before final stream event",
                                    error=str(state_exc),
                                )
                            data["state_version"] = final_state_version
                            metadata = data.get("metadata")
                            if isinstance(metadata, dict) and "clarification" in metadata:
                                data.setdefault("clarification", metadata.get("clarification"))
                            await cognitive_event_bus.publish(
                                cognitive_event_bus.emit_evidence(
                                    trace_id=trace_id,
                                    span_id=trace_ctx.start_span(
                                        SpanStage.FUSION, parent_span_id=gateway_span
                                    ),
                                    parent_span_id=gateway_span,
                                    payload={
                                        "action": "final_answer",
                                        "content": final_content,
                                        "validation_score": data.get("validation_score"),
                                        "route": data.get("route"),
                                    },
                                    session_id=session_id,
                                    request_id=request_id,
                                    user_id=current_user.id,
                                    source="kernel_stream",
                                )
                            )
                        await queue.put(event)
                except asyncio.CancelledError:
                    await cognitive_event_bus.publish(
                        cognitive_event_bus.emit_feedback(
                            trace_id=trace_id,
                            span_id=trace_ctx.start_span(
                                SpanStage.GATEWAY, parent_span_id=gateway_span
                            ),
                            parent_span_id=gateway_span,
                            payload={
                                "action": "stream_cancelled",
                                "session_id": session_id,
                                "request_id": request_id,
                            },
                            session_id=session_id,
                            request_id=request_id,
                            user_id=current_user.id,
                            source="chat_router",
                        )
                    )
                    await queue.put({"type": "aborted", "data": {"message": "Cancelled by user"}})
                    raise
                except Exception as exc:  # noqa: BLE001
                    await cognitive_event_bus.publish(
                        cognitive_event_bus.emit_critic(
                            trace_id=trace_id,
                            span_id=trace_ctx.start_span(
                                SpanStage.CRITIC, parent_span_id=gateway_span
                            ),
                            parent_span_id=gateway_span,
                            payload={"action": "stream_error", "message": str(exc)},
                            session_id=session_id,
                            request_id=request_id,
                            user_id=current_user.id,
                            source="chat_router",
                        )
                    )
                    await queue.put(
                        {"type": "error", "data": {"message": _public_stream_error(exc)}}
                    )
                finally:
                    await queue.put(None)

            try:
                queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
                task = asyncio.create_task(_runner())
                _ACTIVE_STREAM_TASKS[task_key] = task
                _ACTIVE_STREAM_CONTEXTS[task_key] = {
                    "graph_controls": graph_controls,
                    "session_id": session_id,
                    "request_id": request_id,
                    "updated_at": time.time(),
                }
            except Exception as setup_exc:
                logger.error("SSE stream setup failed", error=str(setup_exc))
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(setup_exc)}}, ensure_ascii=False)}\n\n"
                yield ": done\n\n"
                return

            try:
                while True:
                    try:
                        event = await queue.get()
                    except asyncio.CancelledError:
                        yield f"data: {json.dumps({'type': 'aborted', 'data': {'message': 'Cancelled by user'}}, ensure_ascii=False)}\n\n"
                        return

                    if event is None:
                        break
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                task.cancel()
                with contextlib.suppress(Exception):
                    await task
                # Save partial content as interrupted trace
                if final_content:
                    interrupted_content = final_content + "\n\n[回答中断]"
                    asyncio.create_task(
                        _save_trace(
                            session_id,
                            dispatch_query,
                            interrupted_content,
                            int((time.monotonic() - t0) * 1000),
                            "interrupted",
                            1.0,
                            final_reasoning_steps,
                            final_execution_graph,
                            parent_message_id=req.parent_message_id,
                            attachment_ids=req.attachment_ids,
                        )
                    )
                yield f"data: {json.dumps({'type': 'aborted', 'data': {'message': 'Cancelled by user'}}, ensure_ascii=False)}\n\n"
                return
            except Exception as exc:  # noqa: BLE001
                logger.error("Kernel stream error", error=str(exc))
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': _public_stream_error(exc)}}, ensure_ascii=False)}\n\n"
                return
            finally:
                _ACTIVE_STREAM_TASKS.pop(task_key, None)
                _ACTIVE_STREAM_CONTEXTS.pop(task_key, None)
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(Exception):
                        await task

            latency_ms = int((time.monotonic() - t0) * 1000)
            asyncio.create_task(
                _save_trace(
                    session_id,
                    dispatch_query,
                    final_content,
                    latency_ms,
                    "kernel",
                    1.0,
                    final_reasoning_steps,
                    final_execution_graph,
                    parent_message_id=req.parent_message_id,
                    attachment_ids=req.attachment_ids,
                )
            )
            if req.memory_mode == "enabled" and await _memory_learning_enabled(db, current_user.id):
                asyncio.create_task(
                    _save_user_memory_from_turn(current_user.id, dispatch_query, final_content)
                )
            tools_used = []
            try:
                tools_used = [
                    str(x)
                    for x in (
                        ((final_execution_graph or {}).get("state") or {}).get("tools_used") or []
                    )
                ]
            except Exception:
                tools_used = []
            if tools_used:
                tool_anomaly_detector.record(tools_used)
                if tool_anomaly_detector.is_anomalous(tools_used):
                    asyncio.create_task(
                        write_audit_log(
                            user_id=current_user.id,
                            action="security.anomaly.detected",
                            resource_type="tool_sequence",
                            resource_id=session_id,
                            payload={"tools": tools_used},
                        )
                    )
            # ── Persist ConversationState for streaming path ──
            if final_state_patch is not None and not final_state_persisted:
                try:
                    # Reuse state_manager from outer scope; re-load for latest state
                    cs = await state_manager.load(session_id)
                    if cs:
                        state_manager.apply_patch(cs, final_state_patch)
                        state_manager.advance_turn(cs, dispatch_query, final_content)
                        state_manager.add_confidence(
                            cs,
                            cs.turn_sequence,
                            0.85,  # default confidence for stream path
                            components={"route": "kernel_stream"},
                        )
                        state_manager.compact(cs)
                        await state_manager.save(cs)
                except Exception as state_exc:
                    logger.warning(
                        "Failed to persist ConversationState in stream path", error=str(state_exc)
                    )
            # ── End ConversationState persistence ─────────────────────
            yield ": done\n\n"

        return StreamingResponse(
            _sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        kernel = _get_kernel()
        result = await kernel.run(kernel_request)
    except Exception as exc:
        await cognitive_event_bus.publish(
            cognitive_event_bus.emit_critic(
                trace_id=trace_id,
                span_id=trace_ctx.start_span(SpanStage.CRITIC, parent_span_id=gateway_span),
                parent_span_id=gateway_span,
                payload={"action": "kernel_run_error", "message": str(exc)},
                session_id=session_id,
                request_id=request_id,
                user_id=current_user.id,
                source="chat_router",
            )
        )
        logger.error("Kernel run error", error=str(exc), error_code=ErrorCodes.LLM_CALL_FAILED.code)
        if force_database and data_source_context.get("data_source_id"):
            try:
                from gateway.api_gateway.routers.data import DataQueryRequest, data_query

                direct = await data_query(
                    DataQueryRequest(
                        question=dispatch_query,
                        data_source_id=str(data_source_context["data_source_id"]),
                        dry_run=False,
                        sql=None,
                    ),
                    current_user=current_user,
                    db=db,
                    http_request=http_request,
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
                return ChatResponse(
                    session_id=session_id,
                    content=str(
                        direct.get("summary")
                        or direct.get("sql")
                        or direct.get("rows")
                        or "查询完成"
                    ),
                    decision_type="database_fallback",
                    validation_score=0.85,
                    passed_validation=True,
                    intent_category="data_query",
                    context_latency_ms=0,
                    total_latency_ms=latency_ms,
                    citations=[],
                    annotations=[],
                    execution_graph={
                        "route": "data_query",
                        "data_source_id": data_source_context["data_source_id"],
                        "sql": direct.get("sql"),
                        "rows": direct.get("rows", [])[:20],
                    },
                )
            except Exception as db_exc:  # noqa: BLE001
                logger.warning("Database fallback failed", error=str(db_exc))
        fallback = "当前模型服务不可用，请稍后重试。"
        latency_ms = int((time.monotonic() - t0) * 1000)
        await cognitive_event_bus.publish(
            cognitive_event_bus.emit_critic(
                trace_id=trace_id,
                span_id=trace_ctx.start_span(SpanStage.CRITIC, parent_span_id=gateway_span),
                parent_span_id=gateway_span,
                payload={"action": "fallback_used", "reason": str(exc)},
                session_id=session_id,
                request_id=request_id,
                user_id=current_user.id,
                source="chat_router",
            )
        )
        asyncio.create_task(
            _save_trace(
                session_id,
                dispatch_query,
                fallback,
                latency_ms,
                "fallback",
                0.0,
                parent_message_id=req.parent_message_id,
                attachment_ids=req.attachment_ids,
            )
        )
        return ChatResponse(
            session_id=session_id,
            content=fallback,
            decision_type="fallback",
            validation_score=0.0,
            passed_validation=False,
            intent_category="fallback",
            context_latency_ms=0,
            total_latency_ms=latency_ms,
        )

    latency_ms = int((time.monotonic() - t0) * 1000)
    final_content = (
        result.content or ""
    ).strip() or "我已经完成了分析，但当前没有可直接展示的最终答案。请补充更多信息后再试。"
    final_content = _sanitize_assistant_output(final_content)
    await cognitive_event_bus.publish(
        cognitive_event_bus.emit_learning(
            trace_id=trace_id,
            span_id=trace_ctx.start_span(SpanStage.FINAL, parent_span_id=gateway_span),
            parent_span_id=gateway_span,
            payload={
                "action": "kernel_run_completed",
                "route": result.route,
                "validation_score": result.validation_score,
                "passed_validation": result.passed_validation,
                "intent_category": result.intent_category,
            },
            session_id=session_id,
            request_id=request_id,
            user_id=current_user.id,
            source="chat_router",
        )
    )
    asyncio.create_task(
        _save_trace(
            session_id,
            dispatch_query,
            final_content,
            latency_ms,
            result.route,
            result.validation_score,
            result.metadata.get("steps") if isinstance(result.metadata, dict) else None,
            result.metadata.get("execution_graph") if isinstance(result.metadata, dict) else None,
            parent_message_id=req.parent_message_id,
            attachment_ids=req.attachment_ids,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            model=(
                result.model or result.metadata.get("model", "")
                if isinstance(result.metadata, dict)
                else ""
            ),
        )
    )
    if req.memory_mode == "enabled" and await _memory_learning_enabled(db, current_user.id):
        asyncio.create_task(_save_user_memory_from_turn(current_user.id, dispatch_query, final_content))

    # ── Persist state_patch to ConversationState ──
    final_state_version = conversation_state.state_version
    if result.state_patch is not None:
        updated_state = state_manager.apply_patch(conversation_state, result.state_patch)
        updated_state = state_manager.advance_turn(updated_state, dispatch_query, final_content)
        state_manager.add_confidence(
            updated_state,
            updated_state.turn_sequence,
            result.validation_score,
            components={
                "fusion": result.validation_score,
                "route": result.route,
            },
        )
        updated_state = state_manager.compact(updated_state)
        final_state_version = updated_state.state_version
        asyncio.create_task(state_manager.save(updated_state))
    else:
        # Still advance turn counter even if no state_patch
        conversation_state = state_manager.advance_turn(conversation_state, dispatch_query, final_content)
        state_manager.add_confidence(
            conversation_state,
            conversation_state.turn_sequence,
            result.validation_score,
            components={"route": result.route},
        )
        final_state_version = conversation_state.state_version
        asyncio.create_task(state_manager.save(conversation_state))
    # ── End state persistence ──────────────────────────────────

    return ChatResponse(
        session_id=session_id,
        content=final_content,
        decision_type=result.route,
        validation_score=result.validation_score,
        passed_validation=result.passed_validation,
        intent_category=result.intent_category,
        context_latency_ms=result.context_latency_ms,
        total_latency_ms=result.total_latency_ms,
        citations=(
            result.metadata.get("citations", []) if isinstance(result.metadata, dict) else []
        ),
        evidence_refs=(
            result.metadata.get("evidence_refs", []) if isinstance(result.metadata, dict) else []
        ),
        knowledge_operations=(
            result.metadata.get("knowledge_operations", []) if isinstance(result.metadata, dict) else []
        ),
        confidence=(
            result.metadata.get("confidence", result.validation_score)
            if isinstance(result.metadata, dict)
            else result.validation_score
        ),
        uncertainty=(
            result.metadata.get("uncertainty", []) if isinstance(result.metadata, dict) else []
        ),
        trace_id=(
            result.metadata.get("trace_id", trace_id) if isinstance(result.metadata, dict) else trace_id
        ),
        annotations=(
            result.metadata.get("annotations", []) if isinstance(result.metadata, dict) else []
        ),
        execution_graph=(
            result.metadata.get("execution_graph") if isinstance(result.metadata, dict) else None
        ),
        result_refs=result.result_refs if isinstance(result.result_refs, list) else [],
        state_version=final_state_version,
    )


@router.post("/chat/stop")
async def stop_chat_stream(
    req: StopStreamRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    r = await db.execute(
        select(ChatSession).where(
            ChatSession.id == req.session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    if r.scalar_one_or_none() is None:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code, message="Session not found or no permission"
        )

    if req.request_id:
        task_key = f"{req.session_id}:{req.request_id}"
        task = _ACTIVE_STREAM_TASKS.get(task_key)
        if task and not task.done():
            task.cancel()
            return {"stopped": True}
        return {"stopped": False}

    prefix = f"{req.session_id}:"
    stopped = False
    for key, task in list(_ACTIVE_STREAM_TASKS.items()):
        if key.startswith(prefix) and not task.done():
            task.cancel()
            stopped = True
    return {"stopped": stopped}


@router.post("/chat/graph-control")
async def graph_control_chat_stream(
    req: GraphControlRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    r = await db.execute(
        select(ChatSession).where(
            ChatSession.id == req.session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    if r.scalar_one_or_none() is None:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code, message="Session not found or no permission"
        )

    matched_keys: list[str] = []
    if req.request_id:
        matched_keys = [f"{req.session_id}:{req.request_id}"]
    else:
        prefix = f"{req.session_id}:"
        matched_keys = [k for k in _ACTIVE_STREAM_TASKS.keys() if k.startswith(prefix)]

    updated = 0
    for key in matched_keys:
        ctx = _ACTIVE_STREAM_CONTEXTS.get(key)
        if not ctx:
            continue
        controls = ctx.setdefault("graph_controls", {"pruned_nodes": [], "expanded_nodes": []})
        pruned = controls.setdefault("pruned_nodes", [])
        expanded = controls.setdefault("expanded_nodes", [])

        if req.action == "prune" and req.node_id not in pruned:
            pruned.append(req.node_id)
            updated += 1
        if req.action == "expand" and req.node_id not in expanded:
            expanded.append(req.node_id)
            updated += 1
        ctx["updated_at"] = time.time()

    return {
        "updated": updated,
        "session_id": req.session_id,
        "action": req.action,
        "node_id": req.node_id,
        "active_streams": len(matched_keys),
    }


@router.post("/chat/regenerate", response_model=None)
@require_kernel_entrypoint
async def regenerate_chat(
    req: RegenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = await _build_regenerate_query(db, req.session_id)
    chat_req = ChatRequest(
        query=query,
        session_id=req.session_id,
        stream=req.stream,
        web_enabled=req.web_enabled,
    )
    return await chat(chat_req, current_user, db)


@router.post("/chat/edit-and-regenerate", response_model=None)
@require_kernel_entrypoint
async def edit_and_regenerate_chat(
    req: EditRegenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(ChatSession).where(
            ChatSession.id == req.session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    if r.scalar_one_or_none() is None:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code, message="Session not found or no permission"
        )

    query = await _build_edit_regenerate_query(
        db, req.session_id, req.message_id, req.new_content.strip()
    )
    chat_req = ChatRequest(
        query=query,
        session_id=req.session_id,
        stream=req.stream,
        web_enabled=req.web_enabled,
    )
    return await chat(chat_req, current_user, db)


@router.post("/chat/feedback")
async def chat_feedback(
    req: ChatFeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record explicit feedback (like/dislike) on a memory chunk or message.

    Updates the EvolutionMemoryRouter value scoring and persists to the
    Feedback model for future retrieval.
    """
    r = await db.execute(
        select(ChatSession).where(
            ChatSession.id == req.session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    if r.scalar_one_or_none() is None:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code, message="Session not found or no permission"
        )

    # Persist to Feedback model
    feedback = Feedback(
        id=str(uuid.uuid4()),
        session_id=req.session_id,
        query="",
        response="",
        feedback_type=req.feedback_type,
        score=req.score,
        correction=req.correction,
        feedback_metadata=json.dumps(
            {"chunk_id": req.chunk_id, "message_id": req.message_id},
            ensure_ascii=False,
        ),
    )
    db.add(feedback)
    await db.commit()

    # Update EvolutionMemoryRouter value scoring
    chunk_id = req.chunk_id
    if not chunk_id and req.message_id:
        # Look up chunk from message's trace log
        r2 = await db.execute(
            select(TraceLog).where(
                TraceLog.id == req.message_id,
                TraceLog.session_id == req.session_id,
            )
        )
        trace = r2.scalar_one_or_none()
        if trace and trace.execution_graph_json:
            try:
                graph = json.loads(trace.execution_graph_json)
                if isinstance(graph, dict):
                    chunk_id = graph.get("memory_chunk_id")
            except Exception as exc:
                logger.warning("Chat API operation failed", error=str(exc))

    if chunk_id:
        try:
            from memory.evolution.router import EvolutionMemoryRouter
            from memory.memory_router.router import get_memory_router

            router = get_memory_router()
            if isinstance(router, EvolutionMemoryRouter):
                await router.record_feedback(chunk_id, req.feedback_type)

                # Also apply score adjustment to UserMemory if score provided
                if req.score is not None:
                    try:
                        from infra.storage.models import UserMemory as UM

                        r3 = await db.execute(select(UM).where(UM.metadata_json.contains(chunk_id)))
                        mem = r3.scalar_one_or_none()
                        if mem:
                            mem.score = req.score
                            mem.access_count = (mem.access_count or 0) + 1
                            await db.commit()
                    except Exception as exc:
                        logger.warning("Chat API operation failed", error=str(exc))
        except Exception as exc:
            logger.warning("Chat API operation failed", error=str(exc))

    return {"status": "ok", "feedback_type": req.feedback_type}


@router.get("/chat/messages/{message_id}/versions")
async def get_message_versions(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get all versions of a message for the version tree UI."""
    r = await db.execute(
        select(Message).where(Message.id == message_id)
    )
    root = r.scalar_one_or_none()
    if root is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Message not found")

    # Walk up to root (oldest ancestor)
    current = root
    while current.parent_message_id:
        r2 = await db.execute(
            select(Message).where(Message.id == current.parent_message_id)
        )
        parent = r2.scalar_one_or_none()
        if parent is None:
            break
        current = parent
    root_msg = current

    # Walk down to collect all versions
    versions: list[dict] = []
    queue = [root_msg]
    visited: set[str] = set()
    while queue:
        msg = queue.pop(0)
        if msg.id in visited:
            continue
        visited.add(msg.id)
        versions.append({
            "id": msg.id,
            "version": msg.version,
            "role": msg.role,
            "content": msg.content[:200],
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "parent_message_id": msg.parent_message_id,
        })
        # Get children
        r3 = await db.execute(
            select(Message).where(Message.parent_message_id == msg.id)
        )
        children = r3.scalars().all()
        queue.extend(children)

    return {
        "message_id": message_id,
        "root_id": root_msg.id,
        "versions": versions,
        "total_versions": len(versions),
    }


@router.post("/chat/resume", response_model=ChatResponse)
@require_kernel_entrypoint
async def resume_chat(
    req: ResumeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    r = await db.execute(
        select(ChatSession).where(
            ChatSession.id == req.session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = r.scalar_one_or_none()
    if session is None:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message="Session not found or no permission",
        )

    session_id = req.session_id
    set_user_session_context(user_id=current_user.id, session_id=session_id)

    from kernel.runtime.resume_turn import resume_turn_via_gateway

    try:
        result = await resume_turn_via_gateway(
            db,
            session_id=session_id,
            user_id=current_user.id,
            step_index=req.step_index,
        )
    except ValueError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc)) from exc
    return ChatResponse(
        session_id=session_id,
        content=result.content,
        decision_type=result.route,
        validation_score=result.validation_score,
        passed_validation=result.passed_validation,
        intent_category=result.intent_category,
        context_latency_ms=getattr(result, "context_latency_ms", 0) or 0,
        total_latency_ms=getattr(result, "total_latency_ms", 0) or 0,
        execution_graph=(
            result.metadata.get("execution_graph") if isinstance(result.metadata, dict) else None
        ),
        result_refs=result.result_refs if isinstance(result.result_refs, list) else [],
    )
