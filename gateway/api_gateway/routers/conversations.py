"""
Conversations router — list, create, rename, archive, delete, history per user.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from infra.errors import AppException, ErrorCodes
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import Attachment, ChatSession, ConversationState, Feedback, ReasoningTrace, ToolStat, TraceLog, User

router = APIRouter()


def _normalize_reasoning_steps(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []

    normalized: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if "stage" in item and "id" in item:
            normalized.append(item)
            continue

        step_type = item.get("step_type")
        step_id = item.get("step_id")
        if not step_type or not step_id:
            continue

        output = item.get("output") if isinstance(item.get("output"), dict) else {}
        content = ""
        tool = None
        if step_type == "REASON":
            content = str(item.get("reasoning_chain") or output)
        elif step_type == "DECIDE":
            tool_calls = output.get("tool_calls", []) if isinstance(output, dict) else []
            if isinstance(tool_calls, list) and tool_calls:
                names = ", ".join(
                    str(call.get("tool"))
                    for call in tool_calls
                    if isinstance(call, dict) and call.get("tool")
                )
                content = f"选择执行路径并准备调用工具：{names}" if names else "选择执行路径"
                first_call = next(
                    (
                        call
                        for call in tool_calls
                        if isinstance(call, dict) and call.get("tool")
                    ),
                    None,
                )
                if first_call:
                    tool = {
                        "name": str(first_call.get("tool")),
                        "status": "running" if item.get("status") in {"running", "pending"} else "success",
                        "preview": names[:160],
                    }
            else:
                content = "选择直接生成答案路径"
        elif step_type == "EXECUTE":
            tool_results = output.get("tool_results", []) if isinstance(output, dict) else []
            if isinstance(tool_results, list):
                content = "; ".join(
                    f"{result.get('tool')}: {str(result.get('output', ''))[:120]}"
                    for result in tool_results
                    if isinstance(result, dict)
                )
                first_result = next(
                    (
                        result
                        for result in tool_results
                        if isinstance(result, dict) and result.get("tool")
                    ),
                    None,
                )
                if first_result:
                    tool = {
                        "name": str(first_result.get("tool")),
                        "status": "success",
                        "preview": str(first_result.get("output", ""))[:160],
                    }
        elif step_type == "OBSERVE":
            content = str(item.get("observation") or output)
        elif step_type == "REFLECT":
            content = str(
                output.get("issues")
                if isinstance(output, dict) and output.get("issues")
                else output
            )

        normalized.append(
            {
                "id": str(step_id),
                "stage": str(step_type),
                "content": content[:400],
                "status": "running" if item.get("status") in {"running", "pending"} else "done",
                "node_id": item.get("execution_node_id"),
                **({"tool": tool} if tool else {}),
            }
        )
    return normalized


class ConversationOut(BaseModel):
    id: str
    title: Optional[str]
    turn_count: int
    created_at: str
    last_active: str
    archived_at: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    decision_type: Optional[str] = None
    validation_score: Optional[float] = None
    reasoning_steps: list[dict] = Field(default_factory=list)
    execution_graph: Optional[dict] = None
    attachments: list[dict] = Field(default_factory=list)
    tool_calls: Optional[list[dict]] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: Optional[str] = None
    version: int = 1
    status: str = "done"
    metadata: Optional[dict] = None
    citations: list[dict] = Field(default_factory=list)
    annotations: list[dict] = Field(default_factory=list)


class UpdateConversationRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    tags: Optional[list[str]] = None
    pinned: Optional[bool] = None


class ArchiveConversationRequest(BaseModel):
    archived: bool = True


@router.get("/conversations")
async def list_conversations(
    query: str = Query(default="", max_length=200),
    archived: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationOut]:
    clauses = [ChatSession.user_id == current_user.id]
    if archived:
        clauses.append(ChatSession.archived_at.isnot(None))
    else:
        clauses.append(ChatSession.archived_at.is_(None))

    if query.strip():
        q = f"%{query.strip()}%"
        trace_subq = (
            select(TraceLog.session_id)
            .where(TraceLog.query.ilike(q) | TraceLog.response.ilike(q))
            .subquery()
        )
        clauses.append(
            or_(
                ChatSession.title.ilike(q),
                ChatSession.display_title.ilike(q),
                ChatSession.id.in_(select(trace_subq.c.session_id)),
            )
        )

    result = await db.execute(
        select(ChatSession)
        .where(and_(*clauses))
        .order_by(desc(ChatSession.last_active))
        .limit(200)
    )
    sessions = result.scalars().all()
    return [
        ConversationOut(
            id=s.id,
            title=s.display_title or s.title or "New conversation",
            turn_count=s.turn_count,
            created_at=s.created_at.isoformat(),
            last_active=s.last_active.isoformat(),
            archived_at=s.archived_at.isoformat() if s.archived_at else None,
            tags=list(getattr(s, "tags", []) or []),
            pinned=bool(getattr(s, "pinned", False)),
        )
        for s in sessions
    ]


@router.post("/conversations")
async def create_conversation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    session = ChatSession(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        title="New conversation",
        display_title="New conversation",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return ConversationOut(
        id=session.id,
        title=session.display_title or session.title,
        turn_count=0,
        created_at=session.created_at.isoformat(),
        last_active=session.last_active.isoformat(),
        archived_at=None,
        tags=[],
        pinned=False,
    )


@router.patch("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    req: UpdateConversationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == conversation_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Conversation not found")

    if req.title is not None:
        title = req.title.strip()
        session.display_title = title
        session.title = title
    if req.tags is not None:
        session.tags = list(req.tags)
    if req.pinned is not None:
        session.pinned = req.pinned
    await db.commit()
    await db.refresh(session)

    return ConversationOut(
        id=session.id,
        title=session.display_title or session.title,
        turn_count=session.turn_count,
        created_at=session.created_at.isoformat(),
        last_active=session.last_active.isoformat(),
        tags=list(getattr(session, "tags", []) or []),
        pinned=bool(getattr(session, "pinned", False)),
        archived_at=session.archived_at.isoformat() if session.archived_at else None,
    )


@router.post("/conversations/{conversation_id}/archive")
async def archive_conversation(
    conversation_id: str,
    req: ArchiveConversationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == conversation_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Conversation not found")

    session.archived_at = datetime.now(timezone.utc) if req.archived else None
    await db.commit()
    return {"archived": bool(session.archived_at)}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == conversation_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Conversation not found")

    # Explicitly delete ConversationState first to avoid FK constraint issues
    # with passive_deletes=True on the ChatSession.conversation_state relationship.
    cs_result = await db.execute(
        select(ConversationState).where(ConversationState.session_id == conversation_id)
    )
    cs = cs_result.scalar_one_or_none()
    if cs:
        await db.delete(cs)
        await db.flush()

    # Delete attachments explicitly to avoid FK issues if CASCADE wasn't applied in migration
    att_result = await db.execute(
        select(Attachment).where(Attachment.session_id == conversation_id)
    )
    attachments = att_result.scalars().all()
    for att in attachments:
        await db.delete(att)
    if attachments:
        await db.flush()

    # Delete TraceLog entries explicitly to avoid FK constraint issues
    # if CASCADE wasn't applied in migration
    trace_result = await db.execute(
        select(TraceLog).where(TraceLog.session_id == conversation_id)
    )
    traces = trace_result.scalars().all()
    for trace in traces:
        await db.delete(trace)
    if traces:
        await db.flush()

    # Clean up rows that reference session_id without FK constraints
    for model in (ReasoningTrace, ToolStat, Feedback):
        orphan_result = await db.execute(
            select(model).where(model.session_id == conversation_id)
        )
        for row in orphan_result.scalars().all():
            await db.delete(row)
    # Flush after deleting orphan rows if any were found
    # (we already flushed after TraceLog/Attachment, so this is defensive)
    await db.flush()

    await db.delete(session)
    await db.commit()
    return {"deleted": True}


@router.patch("/messages/{message_id}")
async def patch_message(
    message_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not message_id.endswith("_a"):
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Only assistant message can be edited")
    trace_id = message_id[:-2]
    result = await db.execute(
        select(TraceLog)
        .join(ChatSession, ChatSession.id == TraceLog.session_id)
        .where(TraceLog.id == trace_id, ChatSession.user_id == current_user.id)
    )
    log = result.scalar_one_or_none()
    if not log:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Message not found")

    new_content = str(payload.get("content") or "").strip()
    if not new_content:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="content required")

    old = log.response or ""
    log.response = new_content
    await db.commit()

    db.add(
        Feedback(
            id=str(uuid.uuid4()),
            session_id=log.session_id,
            query=log.query,
            response=old,
            feedback_type="correction",
            score=1.0,
            correction=new_content,
            feedback_metadata=json.dumps({"source": "message_patch", "message_id": message_id}, ensure_ascii=False),
        )
    )
    await db.commit()
    return {"updated": True, "message_id": message_id, "content": new_content}


@router.post("/conversations/{conversation_id}/branch")
async def branch_conversation(
    conversation_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    up_to_message_id = str(payload.get("message_id") or "")
    if not up_to_message_id:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="message_id required")

    sess_result = await db.execute(
        select(ChatSession).where(ChatSession.id == conversation_id, ChatSession.user_id == current_user.id)
    )
    sess = sess_result.scalar_one_or_none()
    if not sess:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Conversation not found")

    logs_result = await db.execute(
        select(TraceLog).where(TraceLog.session_id == conversation_id).order_by(TraceLog.created_at)
    )
    logs = logs_result.scalars().all()

    new_id = str(uuid.uuid4())
    new_session = ChatSession(id=new_id, user_id=current_user.id, title=f"{sess.display_title or sess.title} (branch)", display_title=f"{sess.display_title or sess.title} (branch)")
    db.add(new_session)
    await db.commit()

    for log in logs:
        qid = log.id + "_q"
        aid = log.id + "_a"
        new_log = TraceLog(
            id=str(uuid.uuid4()),
            session_id=new_id,
            query=log.query,
            response=log.response,
            decision_type=log.decision_type,
            validation_score=log.validation_score,
            latency_ms=log.latency_ms,
            model=log.model,
            prompt_tokens=log.prompt_tokens,
            completion_tokens=log.completion_tokens,
            reasoning_steps_json=log.reasoning_steps_json,
            execution_graph_json=log.execution_graph_json,
        )
        db.add(new_log)
        if up_to_message_id in {qid, aid}:
            break
    await db.commit()
    return {"conversation_id": new_id, "branched_from": conversation_id, "up_to_message_id": up_to_message_id}


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    sess_result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == conversation_id,
            ChatSession.user_id == current_user.id,
        )
    )
    if not sess_result.scalar_one_or_none():
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Conversation not found")

    logs_result = await db.execute(
        select(TraceLog)
        .where(TraceLog.session_id == conversation_id)
        .order_by(TraceLog.created_at)
        .limit(300)
    )
    logs = logs_result.scalars().all()

    # Query all attachments for this session that are linked to messages
    attachments_result = await db.execute(
        select(Attachment)
        .where(
            Attachment.session_id == conversation_id,
            Attachment.message_id.isnot(None),
            Attachment.status == "active",
        )
    )
    attachments_by_msg: dict[str, list[dict]] = {}
    for att in attachments_result.scalars().all():
        mid = att.message_id or ""
        if mid not in attachments_by_msg:
            attachments_by_msg[mid] = []
        attachments_by_msg[mid].append({
            "id": att.id,
            "filename": att.filename,
            "file_size": att.file_size,
            "file_extension": att.file_extension,
            "mime_type": att.mime_type,
            "content_summary": att.content_summary,
        })

    messages: list[MessageOut] = []
    for log in logs:
        reasoning_steps = []
        execution_graph = None
        if log.reasoning_steps_json:
            try:
                parsed_steps = json.loads(log.reasoning_steps_json)
                reasoning_steps = _normalize_reasoning_steps(parsed_steps)
            except Exception:
                reasoning_steps = []
        if log.execution_graph_json:
            try:
                parsed_graph = json.loads(log.execution_graph_json)
                if isinstance(parsed_graph, dict):
                    execution_graph = parsed_graph
            except Exception:
                execution_graph = None
        user_msg_id = log.id + "_q"
        messages.append(
            MessageOut(
                id=user_msg_id,
                role="user",
                content=log.query,
                created_at=log.created_at.isoformat(),
                attachments=attachments_by_msg.get(user_msg_id, []),
            )
        )
        if log.response:
            meta: dict = {}
            citations: list[dict] = []
            annotations: list[dict] = []
            if isinstance(execution_graph, dict):
                gov = execution_graph.get("governance")
                if isinstance(gov, dict):
                    meta.update(gov)
                meta.setdefault("route", execution_graph.get("route"))
                meta.setdefault("capability_type", execution_graph.get("capability_type"))
                meta.setdefault("agent_type", execution_graph.get("agent_type"))
                if execution_graph.get("needs_clarification"):
                    meta["needs_clarification"] = True
                    meta["turn_outcome"] = meta.get("turn_outcome") or "clarification"
                if isinstance(execution_graph.get("clarification"), dict):
                    meta["clarification"] = execution_graph["clarification"]
            messages.append(
                MessageOut(
                    id=log.id + "_a",
                    role="assistant",
                    content=log.response,
                    created_at=log.created_at.isoformat(),
                    decision_type=log.decision_type,
                    validation_score=log.validation_score,
                    reasoning_steps=reasoning_steps,
                    execution_graph=execution_graph,
                    metadata=meta or None,
                    citations=citations,
                    annotations=annotations,
                    prompt_tokens=int(log.prompt_tokens or 0),
                    completion_tokens=int(log.completion_tokens or 0),
                    model=log.model,
                )
            )
    return messages
