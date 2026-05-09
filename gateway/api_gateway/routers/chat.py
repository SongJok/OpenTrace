"""
Chat router — SSE streaming + sync chat via CognitiveKernel.
All requests flow through the Cognitive Kernel (唯一中枢).
Direct LLM calls are forbidden — only Kernel.run() / Kernel.stream().
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import time
import uuid
from datetime import datetime
from typing import Any, AsyncIterator, Optional

import os
import shutil

from execution.data.query_intents import is_database_question
from infra.config.settings import settings

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from infra.audit.logger import write_audit_log
from infra.errors import AppException, ErrorCodes
from infra.guards.kernel_guard import require_kernel_entrypoint
from infra.message_bus.cognitive_event_bus import cognitive_event_bus
from infra.observability.logger import get_logger
from infra.observability.request_context import get_log_context, set_user_session_context
from infra.security.zero_trust import assess_query_risk, issue_permission_token, tool_anomaly_detector, validate_permission_token
from infra.cache.redis_client import get_cache_redis
from infra.storage.database import AsyncSessionLocal, db_session_dependency as get_db
from infra.storage.models import Attachment, ChatSession, DataSource, DataSourceSchema, Feedback, ReasoningTrace, ToolStat, TraceLog, User, UserMemory, UserMemorySettings
from kernel.protocol.events import SpanStage, trace_context_for_request
from services.file_parser import parse_attachment_content

logger = get_logger(__name__)
router = APIRouter()

_ACTIVE_STREAM_TASKS: dict[str, asyncio.Task] = {}
_ACTIVE_STREAM_CONTEXTS: dict[str, dict[str, Any]] = {}


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=8192)
    session_id: Optional[str] = None
    stream: bool = False
    web_enabled: bool = False
    request_id: Optional[str] = None
    graph_controls: dict[str, Any] = Field(default_factory=dict)
    enabled_skills: list[str] = Field(default_factory=list)
    disabled_skills: list[str] = Field(default_factory=list)
    tool_permission_token: Optional[str] = None
    confirmation_granted: bool = False
    data_source_id: Optional[str] = None
    data_source_name: Optional[str] = None
    force_database: bool = False
    force_mode: Optional[str] = Field(default=None, pattern="^(rag|data_query|data_analysis|anomaly_tracking|product|rule_engine|vision)$")
    # Multi-turn enhancement fields
    clarify_context: Optional[str] = None
    clarify_question_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    attachment_ids: list[str] | None = None
    reference_id: Optional[str] = None
    reference_type: Optional[str] = None
    state_version: Optional[int] = None


class AttachmentUploadResponse(BaseModel):
    attachment_id: str
    content_summary: str
    content_hash: str = ""
    is_duplicate: bool = False


class AttachmentInfo(BaseModel):
    id: str
    filename: str
    file_size: int
    mime_type: Optional[str] = None
    file_extension: Optional[str] = None
    content_summary: Optional[str] = None
    status: str
    message_id: Optional[str] = None
    created_at: str


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
    annotations: list[dict[str, Any]] = Field(default_factory=list)
    execution_graph: Optional[dict[str, Any]] = None
    result_refs: list[dict[str, Any]] = Field(default_factory=list)
    state_version: int = 1


class ResumeRequest(BaseModel):
    session_id: str
    step_index: int = Field(..., ge=0)


class StopStreamRequest(BaseModel):
    session_id: str
    request_id: Optional[str] = None


class GraphControlRequest(BaseModel):
    session_id: str
    request_id: Optional[str] = None
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
    chunk_id: Optional[str] = None
    message_id: Optional[str] = None
    feedback_type: str = Field(..., pattern="^(like|dislike|none)$")
    score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    correction: Optional[str] = Field(default=None, max_length=2048)


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
    except Exception:
        return []


async def _load_branch_checkpoint(
    db: AsyncSession,
    session_id: str,
    message_id: str,
) -> dict[str, Any] | None:
    """Load plan + results from a TraceLog for branching checkpoint reuse."""
    try:
        res = await db.execute(
            select(TraceLog)
            .where(TraceLog.id == message_id, TraceLog.session_id == session_id)
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
    except Exception:
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
    except Exception:
        return None, []


async def _load_conversation_history(
    db: AsyncSession,
    session_id: str,
    limit: int = 10,
) -> list[dict[str, str]]:
    """Load recent conversation turns from trace logs for multi-turn context."""
    try:
        res = await db.execute(
            select(TraceLog)
            .where(TraceLog.session_id == session_id)
            .order_by(TraceLog.created_at.desc())
            .limit(limit)
        )
        logs = res.scalars().all()
        # Reverse to chronological order (oldest first)
        history: list[dict[str, str]] = []
        for log in reversed(logs):
            if log.query:
                history.append({"role": "user", "content": log.query})
            if log.response:
                history.append({"role": "assistant", "content": log.response})
        return history
    except Exception:
        return []


def _is_sql_retrieval_intent(query: str) -> bool:
    """Check if user is asking about the SQL from a *previous* turn.

    Examples: "查询SQL语句是什么？", "刚才的SQL是什么", "执行的SQL"
    These should return the SQL from the previous turn's execution graph.
    """
    q = query.strip().lower()
    if "sql" not in q:
        return False
    sql_retrieval_keywords = [
        "sql语句是什么", "sql是什么", "执行的sql",
        "刚才的sql", "上一步的sql", "之前sql", "sql查询是什么",
        "query sql", "what sql", "生成的sql",
        "sql代码是什么", "查询sql", "本次查询的sql",
    ]
    return any(kw in q for kw in sql_retrieval_keywords)


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
        "帮我写一段sql", "帮我写个sql", "帮我写sql",
        "写一个sql", "写一段sql", "写sql",
        "生成sql", "生成一段sql",
        "帮我写一段 sql", "帮我写个 sql",
        "写一个 sql", "写一段 sql",
        "create a sql", "write a sql", "generate sql",
    ]
    return any(kw in q for kw in sql_gen_keywords)


async def _get_previous_turn_sql(db: AsyncSession, session_id: str) -> str | None:
    """Get the SQL from the most recent *real* data query turn in this session.

    Skips sql_retrieval turns and turns where the query itself was asking
    about SQL. Finds the actual SQL from a real data analysis/count query.
    Handles both direct data_query execution_graphs and orchestrator graphs.
    """
    try:
        res = await db.execute(
            select(TraceLog)
            .where(TraceLog.session_id == session_id)
            .order_by(TraceLog.created_at.desc())
            .limit(30)
        )
        logs = res.scalars().all()
        for log in logs:
            if not log.execution_graph_json:
                continue
            try:
                graph = json.loads(log.execution_graph_json)
                if not isinstance(graph, dict):
                    continue
                route = graph.get("route", "")
                # Skip sql_retrieval turns entirely
                if route == "sql_retrieval":
                    continue
                # Skip turns where the query itself was asking about SQL
                # (these were mishandled and executed a wrong query)
                if log.query and _is_sql_retrieval_intent(log.query):
                    continue
                # Direct data query route: has top-level sql field
                if route in {"database_direct", "data_query", "database_fallback"}:
                    sql = graph.get("sql")
                    if sql:
                        return str(sql)
                # Orchestrator-generated graph: has nodes array
                nodes = graph.get("nodes", [])
                if isinstance(nodes, list) and nodes:
                    for node in nodes:
                        if isinstance(node, dict):
                            node_status = node.get("status", "")
                            # Only accept SQL from successful data agent nodes
                            if node_status == "SUCCESS":
                                metadata = node.get("metadata") or {}
                                agent_type = metadata.get("agent_type", "")
                                if agent_type == "data":
                                    output = node.get("output") or {}
                                    sql = output.get("sql")
                                    if sql:
                                        return str(sql)
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception:
        pass
    return None


async def _ensure_session(session_id: Optional[str], user: User, db: AsyncSession) -> str:
    if session_id:
        r = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id, ChatSession.user_id == user.id
            )
        )
        if r.scalar_one_or_none():
            return session_id
    new_id = session_id or str(uuid.uuid4())
    db.add(ChatSession(id=new_id, user_id=user.id, title="New conversation", display_title="New conversation"))
    await db.commit()
    return new_id


async def _load_user_memory_preferences(db: AsyncSession, user_id: str) -> tuple[list[str], list[str]]:
    """Return (content_list, tags_list) from user preference memories."""
    import json as _json

    r = await db.execute(
        select(UserMemory)
        .where(
            UserMemory.user_id == user_id,
            UserMemory.memory_type == "semantic",
            UserMemory.kind == "preference",
            UserMemory.enabled.is_(True),
        )
        .order_by(UserMemory.pinned.desc(), UserMemory.updated_at.desc())
        .limit(20)
    )
    rows = r.scalars().all()
    contents = [m.content for m in rows if m.content]
    tags: list[str] = []
    for m in rows:
        raw_tags = (m.tags_json or "").strip()
        if not raw_tags:
            continue
        try:
            parsed = _json.loads(raw_tags)
            if isinstance(parsed, list):
                for t in parsed:
                    if isinstance(t, str) and t.strip():
                        tags.append(t.strip())
        except Exception:
            pass
    return contents, tags


def _database_intent(query: str) -> bool:
    return is_database_question(query)


async def _load_data_source_context(
    db: AsyncSession,
    current_user: User,
    data_source_id: str | None,
    query: str | None = None,
    force_database: bool = False,
) -> dict[str, Any]:
    source = None
    if data_source_id:
        r = await db.execute(
            select(DataSource).where(
                DataSource.id == data_source_id,
                DataSource.user_id == current_user.id,
            )
        )
        source = r.scalar_one_or_none()
        if source is None:
            raise AppException(ErrorCodes.PARAM_INVALID.code, message="data source not found")
    elif query:
        q = query.strip().lower()
        if q:
            r = await db.execute(
                select(DataSource)
                .where(DataSource.user_id == current_user.id)
                .order_by(DataSource.created_at.desc())
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
            select(DataSource)
            .where(DataSource.user_id == current_user.id, DataSource.status == "active")
            .order_by(DataSource.updated_at.desc())
            .limit(1)
        )
        source = r.scalar_one_or_none()
    if source is None:
        return {"data_source_id": None, "data_source_name": None, "schema": None}

    rs = await db.execute(select(DataSourceSchema).where(DataSourceSchema.data_source_id == source.id))
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


async def _save_user_memory_from_turn(user_id: str, query: str, response: str) -> None:
    async with AsyncSessionLocal() as db:
        memory = UserMemory(
            id=str(uuid.uuid4()),
            user_id=user_id,
            memory_type="episodic",
            kind="fact",
            title=(query[:64] + ("…" if len(query) > 64 else "")),
            content=f"Q: {query}\nA: {response}",
            enabled=True,
            pinned=False,
        )
        db.add(memory)
        await db.commit()


async def _save_conversation_state_async(state_manager, cs) -> None:
    """Fire-and-forget ConversationState save, never raises."""
    try:
        await state_manager.save(cs)
    except Exception:
        pass


async def _save_trace(
    session_id: str,
    query: str,
    response: str,
    latency_ms: int,
    decision_type: str = "kernel",
    validation_score: float = 1.0,
    reasoning_steps: Optional[list[dict[str, Any]]] = None,
    execution_graph: Optional[dict[str, Any]] = None,
    parent_message_id: Optional[str] = None,
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
                reasoning_steps_json=(json.dumps(reasoning_steps, ensure_ascii=False) if reasoning_steps else None),
                execution_graph_json=(json.dumps(execution_graph, ensure_ascii=False) if execution_graph else None),
            )
            db.add(log)

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
                        content=json.dumps(step, ensure_ascii=False),
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


async def _build_edit_regenerate_query(db: AsyncSession, session_id: str, message_id: str, new_content: str) -> str:
    if message_id.endswith("_q"):
        trace_id = message_id[: -2]
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
    "text/plain", "text/markdown", "text/csv", "text/tab-separated-values",
    "application/pdf", "application/json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
    "image/svg+xml",
}
_ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".log", ".rst", ".csv", ".tsv", ".pdf", ".json", ".jsonl",
    ".docx", ".xlsx", ".xls",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".c", ".cpp", ".h", ".hpp", ".sql", ".sh", ".bash", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".conf", ".html", ".css",
    ".scss", ".less", ".vue", ".svelte",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
}
_ATTACHMENT_TTL = 43200  # 12 hours


@router.post("/chat/attachments", response_model=AttachmentUploadResponse)
async def upload_attachment(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    message_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttachmentUploadResponse:
    """Upload a file attachment, parse content, persist to PostgreSQL, and cache in Redis."""
    if not settings.attachment_upload_enabled:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Attachment upload is disabled")

    # Validate session ownership
    session = await db.scalar(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
    )
    if not session:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Session not found or access denied")

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
    duplicate_of: Optional[str] = None
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

    image_base64: Optional[str] = None
    image_mime: Optional[str] = None
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
        ".xlsx": {"application/vnd.openxmlformats-officedocument", "application/vnd.ms-excel", "application/octet-stream"},
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
        await db.execute(
            select(Attachment)
            .where(
                Attachment.session_id == session_id,
                Attachment.user_id == current_user.id,
                Attachment.status == "active",
            )
            .order_by(Attachment.created_at.desc())
        )
    ).scalars().all()

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
            )
            for att in rows
        ],
        total=len(rows),
    )


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
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Attachment not found or access denied")

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
    except Exception:
        pass

    try:
        session_id = await _ensure_session(req.session_id, current_user, db)
        set_user_session_context(user_id=current_user.id, session_id=session_id)
    
        # Load conversation history for multi-turn support
        conversation_history = await _load_conversation_history(db, session_id, limit=10)
    
        # ── Feature ⑥: Conversation Branching ────────────────────────
        branch_checkpoint: dict[str, Any] | None = None
        is_branch_request = False
        if req.parent_message_id and settings.kernel_conversation_branching_enabled:
            # Roll back history to before the parent message
            history_before = await _load_history_before_message(db, session_id, req.parent_message_id)
            if history_before:
                conversation_history = history_before
            # Load checkpoint from the parent message
            branch_checkpoint = await _load_branch_checkpoint(db, session_id, req.parent_message_id)
            is_branch_request = True
        # ── End Conversation Branching ──────────────────────────────
    
        from kernel.cognitive_kernel import KernelRequest
    
        request_id = req.request_id or str(uuid.uuid4())
        trace_ctx = trace_context_for_request(request_id, session_id=session_id, user_id=current_user.id)
        user_preferences, user_preference_tags = await _load_user_memory_preferences(db, current_user.id)
    
        risk = assess_query_risk(req.query)
        required_permissions = list(risk.required_permissions)
        if required_permissions:
            if not req.tool_permission_token or not await validate_permission_token(session_id, req.tool_permission_token, required_permissions):
                token = await issue_permission_token(session_id, required_permissions)
                await write_audit_log(
                    user_id=current_user.id,
                    action="security.permission.issued",
                    resource_type="session",
                    resource_id=session_id,
                    payload={"required_permissions": required_permissions, "risk_level": risk.risk_level},
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
        data_source_context: dict[str, Any] = {"data_source_id": None, "data_source_name": None, "database": None, "source_type": None, "schema": None}
        data_source_id = (req.data_source_id or "").strip() or None
        force_database = bool(req.force_database) or (_database_intent(req.query) and not _is_sql_generation_intent(req.query) and not _is_sql_retrieval_intent(req.query))
        if force_database and not data_source_id:
            data_source_context = await _load_data_source_context(db, current_user, None, req.query, force_database=True)
        else:
            data_source_context = await _load_data_source_context(db, current_user, data_source_id, None if data_source_id else req.query)
    
        if not data_source_context.get("data_source_id") and not force_database:
            q_lower = req.query.strip().lower()
            internal_intent = any(
                k in q_lower
                for k in [
                    "文档", "手册", "知识库", "项目内", "系统内", "本项目", "内部", "代码", "配置", "规则", "说明", "根据文档", "从文档", "总结", "归纳", "读取", "附件", ".pdf", ".doc", ".docx", ".txt", ".md",
                ]
            )
            if internal_intent:
                data_source_context = await _load_data_source_context(db, current_user, None, req.query)
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
                await db.execute(
                    select(Attachment)
                    .where(
                        Attachment.session_id == session_id,
                        Attachment.status == "active",
                    )
                    .order_by(Attachment.created_at.desc())
                    .limit(_MAX_AUTO_ATTACHMENTS)
                )
            ).scalars().all()
            effective_attachment_ids = [att.id for att in session_attachments]
        if effective_attachment_ids:
            # Batch-load from PostgreSQL
            pg_attachments = (
                await db.execute(
                    select(Attachment).where(
                        Attachment.session_id == session_id,
                        Attachment.id.in_(effective_attachment_ids),
                        Attachment.status == "active",
                    )
                )
            ).scalars().all()
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
            total_content_bytes = 0
            for aid in effective_attachment_ids:
                if aid in pg_map:
                    content = pg_map[aid]
                    total_content_bytes += len(content.encode("utf-8"))
                    if total_content_bytes > _MAX_AUTO_ATTACHMENT_CONTENT_BYTES:
                        break
                    attachment_contexts.append({"attachment_id": aid, "content": content})
    
        # ── Load ConversationState for multi-turn reference resolution ──
        from kernel.conversation_state import ConversationStateManager
        state_manager = ConversationStateManager()
        conversation_state = await state_manager.get_or_create(session_id)
    
        # Merge explicit attachment_ids into ConversationState so they persist across turns
        if req.attachment_ids and any(aid not in conversation_state.active_attachment_ids for aid in req.attachment_ids):
            new_ids = [aid for aid in req.attachment_ids if aid not in conversation_state.active_attachment_ids]
            conversation_state.active_attachment_ids = [*conversation_state.active_attachment_ids, *new_ids]
            asyncio.create_task(_save_conversation_state_async(state_manager, conversation_state))
    
        kernel_request = KernelRequest(
            query=req.query,
            session_id=session_id,
            user_id=current_user.id,
            history=conversation_history,
            stream=req.stream,
            web_enabled=req.web_enabled,
            trace_ctx=trace_ctx,
            conversation_state=conversation_state,
            metadata={
                "request_id": request_id,
                "graph_controls": graph_controls,
                "enabled_skills": req.enabled_skills,
                "disabled_skills": req.disabled_skills,
                "user_preferences": user_preferences,
                "user_preference_tags": user_preference_tags,
                "data_source_id": data_source_context["data_source_id"],
                "data_source_name": data_source_context["data_source_name"],
                "data_source_database": data_source_context.get("database"),
                "data_source_source_type": data_source_context.get("source_type"),
                "data_source_schema": data_source_context["schema"],
                "force_database": force_database,
                "force_mode": req.force_mode,
                # Multi-turn enhancement metadata
                "clarify_context": req.clarify_context,
                "clarify_question_id": req.clarify_question_id,
                "parent_message_id": req.parent_message_id,
                "previous_plan": prev_plan,
                "previous_results": prev_results,
                # Feature ⑥: Conversation Branching
                "resume_mode": is_branch_request,
                "branch_checkpoint": branch_checkpoint,
                "attachment_contexts": attachment_contexts,
            },
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
                "query": req.query,
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

    # SQL retrieval intent: user is asking about the SQL from a previous turn
    # e.g., "查询SQL语句是什么？", "刚才的SQL是什么"
    if _is_sql_retrieval_intent(req.query):
        prev_sql = await _get_previous_turn_sql(db, session_id)
        if prev_sql:
            latency_ms = int((time.monotonic() - t0) * 1000)
            content = f"上一轮查询执行的 SQL 如下：\n\n```sql\n{prev_sql}\n```"
            exec_graph = {"route": "sql_retrieval", "sql": prev_sql}

            # Non-streaming: return direct response
            if not req.stream:
                return ChatResponse(
                    session_id=session_id,
                    content=content,
                    decision_type="sql_retrieval",
                    validation_score=1.0,
                    passed_validation=True,
                    intent_category="sql_retrieval",
                    context_latency_ms=0,
                    total_latency_ms=latency_ms,
                    citations=[],
                    annotations=[],
                    execution_graph=exec_graph,
                )

            # Streaming: emit SSE events
            async def _sse_sql_retrieval() -> AsyncIterator[str]:
                try:
                    yield f"data: {json.dumps({'type': 'reasoning_step', 'data': {'id': 'sql_retrieval', 'stage': 'REASON', 'content': '从上一轮查询中获取 SQL 语句', 'node_id': 'node_sql_retrieval', 'status': 'done'}}, ensure_ascii=False)}\n\n"
                    for i in range(0, len(content), 24):
                        yield f"data: {json.dumps({'type': 'delta', 'data': {'text': content[i : i + 24]}}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'final_answer', 'data': {'content': content, 'execution_graph': exec_graph, 'citations': [], 'annotations': [], 'state_patch': None, 'result_refs': []}}, ensure_ascii=False)}\n\n"
                    yield ": done\n\n"
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("SQL retrieval stream error", error=str(exc))
                    yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(exc)}}, ensure_ascii=False)}\n\n"
                    yield ": done\n\n"

            asyncio.create_task(_save_trace(session_id, req.query, content, latency_ms, "sql_retrieval", 1.0, [], exec_graph, parent_message_id=req.parent_message_id))
            return StreamingResponse(
                _sse_sql_retrieval(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    if force_database and data_source_context.get("data_source_id"):
        try:
            from gateway.api_gateway.routers.data import DataQueryRequest, data_query

            direct = await data_query(
                DataQueryRequest(question=req.query, data_source_id=str(data_source_context["data_source_id"]), dry_run=False, sql=None),
                current_user=current_user,
                db=db,
            )
            direct_sql = direct.get("sql")
            direct_rows = direct.get("rows", [])
            direct_summary = str(direct.get("summary") or direct_sql or direct_rows or "查询完成")
            # If 0 rows returned, provide a helpful message instead of bare summary
            if not direct_rows and "0 行" in direct_summary:
                direct_summary = (
                    f"{direct_summary}\n\n"
                    f"可能原因：数据源中不存在与「{req.query}」相关的表或字段，或查询条件未匹配到数据。\n"
                    "建议：\n"
                    "- 在「数据源」页面检查已连接的表和结构。\n"
                    "- 尝试使用更通用的查询条件，或指定具体的表名。"
                )
            exec_graph = {"route": "data_query", "data_source_id": data_source_context["data_source_id"], "sql": direct_sql, "rows": direct_rows[:20]}

            # Non-streaming: return direct response
            if not req.stream:
                latency_ms = int((time.monotonic() - t0) * 1000)
                return ChatResponse(
                    session_id=session_id,
                    content=direct_summary,
                    decision_type="database_direct",
                    validation_score=0.9,
                    passed_validation=True,
                    intent_category="data_query",
                    context_latency_ms=0,
                    total_latency_ms=latency_ms,
                    citations=[],
                    annotations=[],
                    execution_graph=exec_graph,
                )

            # Streaming: emit SSE events with direct query result (fast path)
            async def _sse_direct_query() -> AsyncIterator[str]:
                task_key = f"{session_id}:{request_id}"
                queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

                async def _runner() -> None:
                    try:
                        # Emit reasoning-like steps for UI feedback
                        yield_reasoning = [
                            {"type": "reasoning_step", "data": {"id": "data_detect", "stage": "REASON", "content": "检测到数据查询请求，正在执行查询", "node_id": "node_data", "status": "done"}},
                            {"type": "dag_node_start", "data": {"node_id": "data_0", "agent_type": "data", "depends_on": []}},
                            {"type": "agent_start", "data": {"agent_type": "data", "task_id": "data_0", "query": req.query}},
                            {"type": "agent_progress", "data": {"agent_type": "data", "task_id": "data_0", "progress": 50, "message": "执行中"}},
                            {"type": "dag_node_complete", "data": {"node_id": "data_0", "agent_type": "data", "status": "success", "preview": str(direct_summary)[:200]}},
                            {"type": "agent_complete", "data": {"agent_type": "data", "task_id": "data_0", "status": "success", "preview": str(direct_summary)[:200]}},
                        ]
                        for event in yield_reasoning:
                            await queue.put(event)

                        # Stream the answer character by character
                        content = direct_summary
                        for i in range(0, len(content), 24):
                            await queue.put({"type": "delta", "data": {"text": content[i : i + 24]}})

                        await queue.put({
                            "type": "final_answer",
                            "data": {
                                "content": content,
                                "execution_graph": exec_graph,
                                "citations": [],
                                "annotations": [],
                                "state_patch": None,
                                "result_refs": [],
                            },
                        })
                    except Exception as exc:  # noqa: BLE001
                        await queue.put({"type": "error", "data": {"message": str(exc)}})
                    finally:
                        await queue.put(None)

                try:
                    task = asyncio.create_task(_runner())
                    _ACTIVE_STREAM_TASKS[task_key] = task
                except Exception as setup_exc:
                    logger.error("Direct query stream setup failed", error=str(setup_exc))
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
                    yield f"data: {json.dumps({'type': 'aborted', 'data': {'message': 'Cancelled by user'}}, ensure_ascii=False)}\n\n"
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.error("Direct query stream error", error=str(exc))
                    yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(exc)}}, ensure_ascii=False)}\n\n"
                    return
                finally:
                    _ACTIVE_STREAM_TASKS.pop(task_key, None)
                    if not task.done():
                        task.cancel()
                        with contextlib.suppress(Exception):
                            await task

                latency_ms = int((time.monotonic() - t0) * 1000)
                asyncio.create_task(
                    _save_trace(session_id, req.query, direct_summary, latency_ms, "database_direct", 0.9, [], exec_graph, parent_message_id=req.parent_message_id)
                )
                yield ": done\n\n"

            return StreamingResponse(
                _sse_direct_query(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        except Exception as db_exc:  # noqa: BLE001
            logger.warning("Database direct path failed, fallback to kernel", error=str(db_exc))

    if req.stream:

        async def _sse() -> AsyncIterator[str]:
            final_content = ""
            final_execution_graph: dict[str, Any] | None = None
            final_reasoning_steps: list[dict[str, Any]] = []
            final_state_patch: dict[str, Any] | None = None
            task_key = f"{session_id}:{request_id}"

            async def _runner() -> None:
                nonlocal final_content, final_execution_graph, final_reasoning_steps, final_state_patch
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
                                    span_id=trace_ctx.start_span(SpanStage.AGENT_EXECUTION, parent_span_id=gateway_span),
                                    parent_span_id=gateway_span,
                                    payload={"action": "reasoning_step", "data": data},
                                    session_id=session_id,
                                    request_id=request_id,
                                    user_id=current_user.id,
                                    source="kernel_stream",
                                )
                            )
                        elif event_type == "final_answer" and isinstance(data, dict):
                            final_content = str(data.get("content", ""))
                            graph = data.get("execution_graph")
                            if isinstance(graph, dict):
                                final_execution_graph = graph
                            final_state_patch = data.get("state_patch")
                            if isinstance(final_state_patch, dict):
                                pass  # captured, will be persisted below
                            else:
                                final_state_patch = None
                            await cognitive_event_bus.publish(
                                cognitive_event_bus.emit_evidence(
                                    trace_id=trace_id,
                                    span_id=trace_ctx.start_span(SpanStage.FUSION, parent_span_id=gateway_span),
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
                            span_id=trace_ctx.start_span(SpanStage.GATEWAY, parent_span_id=gateway_span),
                            parent_span_id=gateway_span,
                            payload={"action": "stream_cancelled", "session_id": session_id, "request_id": request_id},
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
                            span_id=trace_ctx.start_span(SpanStage.CRITIC, parent_span_id=gateway_span),
                            parent_span_id=gateway_span,
                            payload={"action": "stream_error", "message": str(exc)},
                            session_id=session_id,
                            request_id=request_id,
                            user_id=current_user.id,
                            source="chat_router",
                        )
                    )
                    await queue.put({"type": "error", "data": {"message": str(exc)}})
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
                yield f"data: {json.dumps({'type': 'aborted', 'data': {'message': 'Cancelled by user'}}, ensure_ascii=False)}\n\n"
                return
            except Exception as exc:  # noqa: BLE001
                logger.error("Kernel stream error", error=str(exc))
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(exc)}}, ensure_ascii=False)}\n\n"
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
                    req.query,
                    final_content,
                    latency_ms,
                    "kernel",
                    1.0,
                    final_reasoning_steps,
                    final_execution_graph,
                    parent_message_id=req.parent_message_id,
                )
            )
            if await _memory_learning_enabled(db, current_user.id):
                asyncio.create_task(_save_user_memory_from_turn(current_user.id, req.query, final_content))
            tools_used = []
            try:
                tools_used = [str(x) for x in (((final_execution_graph or {}).get("state") or {}).get("tools_used") or [])]
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
            if final_state_patch is not None:
                try:
                    # Reuse state_manager from outer scope; re-load for latest state
                    cs = await state_manager.load(session_id)
                    if cs:
                        state_manager.apply_patch(cs, final_state_patch)
                        state_manager.compact(cs)
                        await state_manager.save(cs)
                except Exception as state_exc:
                    logger.warning("Failed to persist ConversationState in stream path", error=str(state_exc))
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
                    DataQueryRequest(question=req.query, data_source_id=str(data_source_context["data_source_id"]), dry_run=False, sql=None),
                    current_user=current_user,
                    db=db,
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
                return ChatResponse(
                    session_id=session_id,
                    content=str(direct.get("summary") or direct.get("sql") or direct.get("rows") or "查询完成"),
                    decision_type="database_fallback",
                    validation_score=0.85,
                    passed_validation=True,
                    intent_category="data_query",
                    context_latency_ms=0,
                    total_latency_ms=latency_ms,
                    citations=[],
                    annotations=[],
                    execution_graph={"route": "data_query", "data_source_id": data_source_context["data_source_id"], "sql": direct.get("sql"), "rows": direct.get("rows", [])[:20]},
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
                req.query,
                fallback,
                latency_ms,
                "fallback",
                0.0,
                parent_message_id=req.parent_message_id,
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
    final_content = (result.content or "").strip() or "我已经完成了分析，但当前没有可直接展示的最终答案。请补充更多信息后再试。"
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
            req.query,
            final_content,
            latency_ms,
            result.route,
            result.validation_score,
            result.metadata.get("steps") if isinstance(result.metadata, dict) else None,
            result.metadata.get("execution_graph") if isinstance(result.metadata, dict) else None,
            parent_message_id=req.parent_message_id,
        )
    )
    if await _memory_learning_enabled(db, current_user.id):
        asyncio.create_task(_save_user_memory_from_turn(current_user.id, req.query, final_content))

    # ── Persist state_patch to ConversationState ──
    if result.state_patch is not None:
        updated_state = state_manager.apply_patch(conversation_state, result.state_patch)
        updated_state = state_manager.compact(updated_state)
        asyncio.create_task(state_manager.save(updated_state))
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
        citations=(result.metadata.get("citations", []) if isinstance(result.metadata, dict) else []),
        annotations=(result.metadata.get("annotations", []) if isinstance(result.metadata, dict) else []),
        execution_graph=(result.metadata.get("execution_graph") if isinstance(result.metadata, dict) else None),
        result_refs=result.result_refs if isinstance(result.result_refs, list) else [],
        state_version=conversation_state.state_version,
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
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Session not found or no permission")

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
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Session not found or no permission")

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
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Session not found or no permission")

    query = await _build_edit_regenerate_query(db, req.session_id, req.message_id, req.new_content.strip())
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
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Session not found or no permission")

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
            except Exception:
                pass

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
                        r3 = await db.execute(
                            select(UM).where(UM.metadata_json.contains(chunk_id))
                        )
                        mem = r3.scalar_one_or_none()
                        if mem:
                            mem.score = req.score
                            mem.access_count = (mem.access_count or 0) + 1
                            await db.commit()
                    except Exception:
                        pass
        except Exception:
            pass

    return {"status": "ok", "feedback_type": req.feedback_type}


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

    from kernel.orchestrator import CognitiveOrchestrator

    orchestrator = CognitiveOrchestrator()
    try:
        result = await orchestrator.resume(session_id=session_id, step_index=req.step_index)
    except ValueError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc)) from exc
    return ChatResponse(
        session_id=session_id,
        content=result.content,
        decision_type=result.route,
        validation_score=result.validation_score,
        passed_validation=result.passed_validation,
        intent_category=result.intent_category,
        context_latency_ms=0,
        total_latency_ms=0,
    )
