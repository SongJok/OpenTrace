"""
Chat router — SSE streaming + sync chat via CognitiveKernel.
All requests flow through the Cognitive Kernel (唯一中枢).
Direct LLM calls are forbidden — only Kernel.run() / Kernel.stream().
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from datetime import datetime
from typing import Any, AsyncIterator, Optional

from execution.data.query_intents import is_database_question
from fastapi import APIRouter, Depends
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
from infra.storage.database import AsyncSessionLocal, db_session_dependency as get_db
from infra.storage.models import ChatSession, DataSource, DataSourceSchema, ReasoningTrace, ToolStat, TraceLog, User, UserMemory, UserMemorySettings

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
    force_mode: Optional[str] = Field(default=None, pattern="^(rag|data_query|data_analysis|anomaly_tracking)$")


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


async def _load_user_memory_preferences(db: AsyncSession, user_id: str) -> list[str]:
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
    return [m.content for m in r.scalars().all() if m.content]


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


async def _save_trace(
    session_id: str,
    query: str,
    response: str,
    latency_ms: int,
    decision_type: str = "kernel",
    validation_score: float = 1.0,
    reasoning_steps: Optional[list[dict[str, Any]]] = None,
    execution_graph: Optional[dict[str, Any]] = None,
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            ctx = get_log_context()
            trace_id = ctx.get("trace_id") or None
            log = TraceLog(
                id=str(uuid.uuid4()),
                session_id=session_id,
                trace_id=trace_id,
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

    session_id = await _ensure_session(req.session_id, current_user, db)
    set_user_session_context(user_id=current_user.id, session_id=session_id)

    from kernel.cognitive_kernel import KernelRequest

    request_id = req.request_id or str(uuid.uuid4())
    user_preferences = await _load_user_memory_preferences(db, current_user.id)

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
    force_database = bool(req.force_database) or _database_intent(req.query)
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
    kernel_request = KernelRequest(
        query=req.query,
        session_id=session_id,
        user_id=current_user.id,
        stream=req.stream,
        web_enabled=req.web_enabled,
        metadata={
            "request_id": request_id,
            "graph_controls": graph_controls,
            "enabled_skills": req.enabled_skills,
            "disabled_skills": req.disabled_skills,
            "user_preferences": user_preferences,
            "data_source_id": data_source_context["data_source_id"],
            "data_source_name": data_source_context["data_source_name"],
            "data_source_database": data_source_context.get("database"),
            "data_source_source_type": data_source_context.get("source_type"),
            "data_source_schema": data_source_context["schema"],
            "force_database": force_database,
            "force_mode": req.force_mode,
        },
    )

    t0 = time.monotonic()
    trace_id = get_log_context().get("trace_id") or request_id
    await cognitive_event_bus.publish(
        cognitive_event_bus.emit_planning(
            trace_id=trace_id,
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
                            },
                        })
                    except Exception as exc:  # noqa: BLE001
                        await queue.put({"type": "error", "data": {"message": str(exc)}})
                    finally:
                        await queue.put(None)

                task = asyncio.create_task(_runner())
                _ACTIVE_STREAM_TASKS[task_key] = task
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
                    _save_trace(session_id, req.query, direct_summary, latency_ms, "database_direct", 0.9, [], exec_graph)
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
            task_key = f"{session_id}:{request_id}"

            async def _runner() -> None:
                nonlocal final_content, final_execution_graph, final_reasoning_steps
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
                            await cognitive_event_bus.publish(
                                cognitive_event_bus.emit_evidence(
                                    trace_id=trace_id,
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

            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            task = asyncio.create_task(_runner())
            _ACTIVE_STREAM_TASKS[task_key] = task
            _ACTIVE_STREAM_CONTEXTS[task_key] = {
                "graph_controls": graph_controls,
                "session_id": session_id,
                "request_id": request_id,
                "updated_at": time.time(),
            }
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
        )
    )
    if await _memory_learning_enabled(db, current_user.id):
        asyncio.create_task(_save_user_memory_from_turn(current_user.id, req.query, final_content))
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
