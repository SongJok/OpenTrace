"""Canonical conversation and branch resources backed only by Responses/Items."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.model_settings import snapshot_runtime_llm_selection
from infra.responses.repository import add_outbox, append_event
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    AssistantProfile,
    Attachment,
    ChatSession,
    ConversationShare,
    MemoryEvidence,
    ResponseApproval,
    ResponseItem,
    ResponseRecord,
    User,
    UserMemory,
)

router = APIRouter()


class ConversationOut(BaseModel):
    id: str
    title: str | None
    turn_count: int
    created_at: str
    last_active: str
    archived_at: str | None = None
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False
    is_temporary: bool = False
    expires_at: str | None = None
    assistant_profile_id: str | None = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    model: str | None = None
    status: str = "done"
    metadata: dict | None = None
    citations: list[dict] = Field(default_factory=list)
    annotations: list[dict] = Field(default_factory=list)
    response_id: str | None = None
    parent_response_id: str | None = None
    version_index: int = 1
    sibling_count: int = 1
    reasoning_steps: list[dict] = Field(default_factory=list)
    execution_graph: dict | None = None
    attachments: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    version: int = 1
    approvals: list[dict] = Field(default_factory=list)


class UpdateConversationRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    tags: list[str] | None = None
    pinned: bool | None = None
    assistant_profile_id: str | None = None
    instructions: str | None = Field(default=None, max_length=8000)


class ArchiveConversationRequest(BaseModel):
    archived: bool = True


class CreateConversationRequest(BaseModel):
    temporary: bool = False
    assistant_profile_id: str | None = None
    instructions: str | None = Field(default=None, max_length=8000)


class ActiveResponseRequest(BaseModel):
    response_id: str


def _conversation_out(session: ChatSession) -> ConversationOut:
    return ConversationOut(
        id=session.id,
        title=session.display_title or session.title or "New conversation",
        turn_count=int(session.turn_count or 0),
        created_at=session.created_at.isoformat(),
        last_active=session.last_active.isoformat(),
        archived_at=session.archived_at.isoformat() if session.archived_at else None,
        tags=list(session.tags or []),
        pinned=bool(session.pinned),
        is_temporary=bool(session.is_temporary),
        expires_at=session.expires_at.isoformat() if session.expires_at else None,
        assistant_profile_id=session.assistant_profile_id,
    )


def _approval_payloads(approvals: list[ResponseApproval]) -> list[dict]:
    return [
        {
            "id": item.id,
            "call_id": item.call_id,
            "tool_name": item.tool_name,
            "side_effect": item.side_effect_level,
            "operation_class": item.operation_class,
            "arguments": dict(item.arguments or {}),
        }
        for item in approvals
    ]


def _project_response_approvals(
    response: ResponseRecord,
    response_messages: list[MessageOut],
    approvals: list[dict],
    *,
    version_index: int,
    sibling_count: int,
) -> list[MessageOut]:
    for index in range(len(response_messages) - 1, -1, -1):
        if response_messages[index].role != "assistant":
            continue
        if approvals:
            response_messages[index] = response_messages[index].model_copy(
                update={"approvals": approvals}
            )
        return response_messages
    if response.status not in {"queued", "in_progress", "requires_action"}:
        return response_messages
    response_messages.append(
        MessageOut(
            id=f"pending_{response.id}",
            role="assistant",
            content="",
            created_at=response.created_at.isoformat(),
            model=response.model,
            status=response.status,
            response_id=response.id,
            parent_response_id=response.parent_response_id,
            version=response.version,
            version_index=version_index,
            sibling_count=sibling_count,
            approvals=approvals,
        )
    )
    return response_messages


def _scope(request: Request, user_id: str) -> tuple[str, str, str]:
    metadata = build_tenant_metadata(request, user_id=user_id)
    return (
        str(metadata.get("tenant_id") or "default"),
        str(metadata.get("org_id") or "default"),
        str(metadata.get("workspace_id") or "default"),
    )


async def _owned_session(
    db: AsyncSession,
    conversation_id: str,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
) -> ChatSession:
    session = await db.scalar(
        select(ChatSession).where(
            ChatSession.id == conversation_id,
            ChatSession.user_id == user_id,
            ChatSession.tenant_id == tenant_id,
            ChatSession.workspace_id == workspace_id,
        )
    )
    if session is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Conversation not found")
    return session


async def _validate_assistant_profile(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    assistant_profile_id: str | None,
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


async def _active_chain(
    db: AsyncSession,
    session: ChatSession,
    user_id: str,
    *,
    starting_response_id: str | None = None,
) -> list[ResponseRecord]:
    current_id = starting_response_id or session.active_response_id
    if not current_id:
        latest = await db.scalar(
            select(ResponseRecord)
            .where(ResponseRecord.conversation_id == session.id, ResponseRecord.user_id == user_id)
            .order_by(ResponseRecord.created_at.desc())
            .limit(1)
        )
        current_id = latest.id if latest else None
    by_id: dict[str, ResponseRecord] = {}
    while current_id and current_id not in by_id:
        row = await db.scalar(
            select(ResponseRecord).where(
                ResponseRecord.id == current_id,
                ResponseRecord.user_id == user_id,
                ResponseRecord.conversation_id == session.id,
            )
        )
        if row is None:
            break
        by_id[row.id] = row
        current_id = row.parent_response_id
    return list(reversed(list(by_id.values())))


async def _items_for(db: AsyncSession, response_ids: list[str]) -> dict[str, list[ResponseItem]]:
    if not response_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(ResponseItem)
                .where(ResponseItem.response_id.in_(response_ids))
                .order_by(ResponseItem.created_at, ResponseItem.sequence_number)
            )
        )
        .scalars()
        .all()
    )
    result: dict[str, list[ResponseItem]] = {}
    for item in rows:
        result.setdefault(item.response_id, []).append(item)
    return result


def _share_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@router.get("/conversations")
async def list_conversations(
    request: Request,
    query: str = Query(default="", max_length=200),
    archived: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationOut]:
    tenant_id, _org_id, workspace_id = _scope(request, current_user.id)
    clauses = [
        ChatSession.user_id == current_user.id,
        ChatSession.tenant_id == tenant_id,
        ChatSession.workspace_id == workspace_id,
    ]
    clauses.append(
        ChatSession.archived_at.isnot(None) if archived else ChatSession.archived_at.is_(None)
    )
    if not archived:
        clauses.append(ChatSession.is_temporary.is_(False))
    if query.strip():
        pattern = f"%{query.strip()}%"
        response_sessions = (
            select(ResponseRecord.conversation_id)
            .join(ResponseItem, ResponseItem.response_id == ResponseRecord.id)
            .where(ResponseItem.content.ilike(pattern))
        )
        clauses.append(
            or_(
                ChatSession.title.ilike(pattern),
                ChatSession.display_title.ilike(pattern),
                ChatSession.id.in_(response_sessions),
            )
        )
    sessions = (
        (
            await db.execute(
                select(ChatSession)
                .where(and_(*clauses))
                .order_by(desc(ChatSession.pinned), desc(ChatSession.last_active))
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    return [_conversation_out(session) for session in sessions]


@router.post("/conversations")
async def create_conversation(
    request: Request,
    req: CreateConversationRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    payload = req or CreateConversationRequest()
    tenant_id, org_id, workspace_id = _scope(request, current_user.id)
    await _validate_assistant_profile(
        db,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        assistant_profile_id=payload.assistant_profile_id,
    )
    session = ChatSession(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=tenant_id,
        org_id=org_id,
        workspace_id=workspace_id,
        title="New conversation",
        display_title="New conversation",
        is_temporary=payload.temporary,
        expires_at=datetime.now(UTC) + timedelta(days=30) if payload.temporary else None,
        assistant_profile_id=payload.assistant_profile_id,
        conversation_instructions=payload.instructions,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return _conversation_out(session)


@router.patch("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    request: Request,
    req: UpdateConversationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    tenant_id, _org_id, workspace_id = _scope(request, current_user.id)
    session = await _owned_session(db, conversation_id, current_user.id, tenant_id, workspace_id)
    requested_profile_id = (
        req.assistant_profile_id
        if "assistant_profile_id" in req.model_fields_set
        else session.assistant_profile_id
    )
    await _validate_assistant_profile(
        db,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        assistant_profile_id=requested_profile_id,
    )
    if req.title is not None:
        session.title = session.display_title = req.title.strip()
    if req.tags is not None:
        session.tags = req.tags
    if req.pinned is not None:
        session.pinned = req.pinned
    if "assistant_profile_id" in req.model_fields_set:
        session.assistant_profile_id = req.assistant_profile_id or None
    if req.instructions is not None:
        session.conversation_instructions = req.instructions.strip() or None
    await db.commit()
    await db.refresh(session)
    return _conversation_out(session)


@router.post("/conversations/{conversation_id}/archive")
async def archive_conversation(
    conversation_id: str,
    request: Request,
    req: ArchiveConversationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, _org_id, workspace_id = _scope(request, current_user.id)
    session = await _owned_session(db, conversation_id, current_user.id, tenant_id, workspace_id)
    session.archived_at = datetime.now(UTC) if req.archived else None
    await db.commit()
    return {"archived": bool(session.archived_at)}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, _org_id, workspace_id = _scope(request, current_user.id)
    session = await _owned_session(db, conversation_id, current_user.id, tenant_id, workspace_id)
    active_response = await db.scalar(
        select(ResponseRecord.id)
        .where(
            ResponseRecord.conversation_id == session.id,
            ResponseRecord.user_id == current_user.id,
            or_(
                ResponseRecord.status.in_(("queued", "in_progress")),
                and_(
                    ResponseRecord.lease_owner.isnot(None),
                    or_(
                        ResponseRecord.lease_expires_at.is_(None),
                        ResponseRecord.lease_expires_at > datetime.now(UTC),
                    ),
                ),
            ),
        )
        .limit(1)
    )
    if active_response:
        raise AppException(
            ErrorCodes.RESOURCE_EXISTS.code,
            message="Conversation 仍有运行中的 Response，请先取消并等待执行结束",
        )
    scoped_memories = select(UserMemory.id).where(
        UserMemory.user_id == current_user.id,
        UserMemory.tenant_id == tenant_id,
        UserMemory.workspace_id == workspace_id,
        UserMemory.scope_type == "conversation",
        UserMemory.scope_id == session.id,
    )
    await db.execute(delete(MemoryEvidence).where(MemoryEvidence.memory_id.in_(scoped_memories)))
    await db.execute(
        delete(UserMemory).where(
            UserMemory.user_id == current_user.id,
            UserMemory.tenant_id == tenant_id,
            UserMemory.workspace_id == workspace_id,
            UserMemory.scope_type == "conversation",
            UserMemory.scope_id == session.id,
        )
    )
    # 依赖数据库 ON DELETE CASCADE，避免 ORM 为旧 TraceLog 关系做无意义的加载。
    await db.execute(delete(ChatSession).where(ChatSession.id == session.id))
    await db.commit()
    return {"deleted": True}


@router.patch("/messages/{message_id}")
async def edit_message_and_branch(
    message_id: str,
    request: Request,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, _org_id, workspace_id = _scope(request, current_user.id)
    item = await db.scalar(
        select(ResponseItem)
        .join(ResponseRecord, ResponseRecord.id == ResponseItem.response_id)
        .where(
            ResponseItem.id == message_id,
            ResponseRecord.user_id == current_user.id,
            ResponseRecord.tenant_id == tenant_id,
            ResponseRecord.workspace_id == workspace_id,
        )
    )
    if item is None or item.item_type != "input_message":
        raise AppException(
            ErrorCodes.PARAM_INVALID.code, message="Only user input can create an edited branch"
        )
    source = await db.get(ResponseRecord, item.response_id)
    content = str(payload.get("content") or "").strip()
    if source is None or not content:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="content required")
    new_id = f"resp_{uuid.uuid4().hex}"
    request_payload = dict(source.request_payload or {})
    request_payload["input"] = content
    model_selection = await snapshot_runtime_llm_selection(
        db,
        user_id=source.user_id,
        tenant_id=source.tenant_id,
        workspace_id=source.workspace_id,
    )
    branch = ResponseRecord(
        id=new_id,
        conversation_id=source.conversation_id,
        user_id=source.user_id,
        tenant_id=source.tenant_id,
        workspace_id=source.workspace_id,
        parent_response_id=source.parent_response_id,
        request_id=str(uuid.uuid4()),
        status="queued",
        mode="stream",
        model=source.model,
        request_payload=request_payload,
        response_metadata={
            **dict(source.response_metadata or {}),
            "model_selection": model_selection,
        },
        goal_id=source.goal_id,
    )
    db.add(branch)
    await db.flush()
    db.add(
        ResponseItem(
            id=f"item_{uuid.uuid4().hex}",
            response_id=new_id,
            sequence_number=0,
            item_type="input_message",
            role="user",
            content=content,
            payload={"edited_from": item.id},
        )
    )
    await append_event(
        db,
        response_id=new_id,
        event_type="response.created",
        payload={"response_id": new_id, "status": "queued"},
    )
    add_outbox(db, response_id=new_id, suffix="edit")
    session = await db.get(ChatSession, source.conversation_id)
    if session:
        session.active_response_id = new_id
    await db.commit()
    return {"updated": True, "response_id": new_id, "content": content}


@router.post("/conversations/{conversation_id}/branch")
async def branch_conversation(
    conversation_id: str,
    request: Request,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, _org_id, workspace_id = _scope(request, current_user.id)
    source_session = await _owned_session(
        db, conversation_id, current_user.id, tenant_id, workspace_id
    )
    message_id = str(payload.get("message_id") or "")
    item = await db.scalar(
        select(ResponseItem)
        .join(ResponseRecord, ResponseRecord.id == ResponseItem.response_id)
        .where(
            or_(ResponseItem.id == message_id, ResponseRecord.id == message_id),
            ResponseRecord.conversation_id == conversation_id,
            ResponseRecord.user_id == current_user.id,
        )
    )
    if item is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Message not found")
    chain = await _active_chain(
        db,
        source_session,
        current_user.id,
        starting_response_id=item.response_id,
    )
    by_response = await _items_for(db, [row.id for row in chain])
    new_session = ChatSession(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        title=f"{source_session.display_title or source_session.title or 'Conversation'} (branch)",
        display_title=f"{source_session.display_title or source_session.title or 'Conversation'} (branch)",
        tenant_id=source_session.tenant_id,
        org_id=source_session.org_id,
        workspace_id=source_session.workspace_id,
        assistant_profile_id=source_session.assistant_profile_id,
        conversation_instructions=source_session.conversation_instructions,
    )
    db.add(new_session)
    await db.flush()
    id_map: dict[str, str] = {}
    for source in chain:
        copied_id = f"resp_{uuid.uuid4().hex}"
        id_map[source.id] = copied_id
        copied_response = ResponseRecord(
            id=copied_id,
            conversation_id=new_session.id,
            user_id=source.user_id,
            tenant_id=source.tenant_id,
            workspace_id=source.workspace_id,
            parent_response_id=id_map.get(source.parent_response_id or ""),
            request_id=str(uuid.uuid4()),
            status=source.status,
            mode=source.mode,
            model=source.model,
            error_code=source.error_code,
            error_message=source.error_message,
            request_payload=dict(source.request_payload or {}),
            response_metadata={**dict(source.response_metadata or {}), "branched_from": source.id},
            version=source.version,
            completed_at=source.completed_at,
        )
        db.add(copied_response)
        # ResponseItem 只持有纯外键，没有 ORM relationship 可推断插入顺序。
        await db.flush()
        for copied_sequence, source_item in enumerate(by_response.get(source.id, [])):
            db.add(
                ResponseItem(
                    id=f"item_{uuid.uuid4().hex}",
                    response_id=copied_id,
                    sequence_number=copied_sequence,
                    item_type=source_item.item_type,
                    role=source_item.role,
                    content=source_item.content,
                    payload=dict(source_item.payload or {}),
                )
            )
    new_session.active_response_id = id_map.get(item.response_id)
    new_session.branch_root_response_id = id_map.get(chain[0].id) if chain else None
    await db.commit()
    return {
        "conversation_id": new_session.id,
        "branched_from": conversation_id,
        "up_to_message_id": message_id,
    }


@router.post("/conversations/{conversation_id}/active-response")
async def set_active_response(
    conversation_id: str,
    request: Request,
    req: ActiveResponseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, _org_id, workspace_id = _scope(request, current_user.id)
    session = await _owned_session(db, conversation_id, current_user.id, tenant_id, workspace_id)
    response = await db.scalar(
        select(ResponseRecord).where(
            ResponseRecord.id == req.response_id,
            ResponseRecord.conversation_id == conversation_id,
            ResponseRecord.user_id == current_user.id,
        )
    )
    if response is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Response not found")
    session.active_response_id = response.id
    await db.commit()
    return {"active_response_id": response.id}


@router.post("/conversations/{conversation_id}/share")
async def create_share(
    conversation_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, _org_id, workspace_id = _scope(request, current_user.id)
    session = await _owned_session(db, conversation_id, current_user.id, tenant_id, workspace_id)
    if session.is_temporary:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="临时聊天不能分享")
    chain = await _active_chain(db, session, current_user.id)
    by_response = await _items_for(db, [row.id for row in chain])
    messages: list[dict] = []
    for response in chain:
        for item in by_response.get(response.id, []):
            if item.item_type not in {"input_message", "message"} or item.role not in {
                "user",
                "assistant",
            }:
                continue
            item_payload = dict(item.payload or {})
            messages.append(
                {
                    "role": item.role,
                    "content": item.content or "",
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "citations": [
                        {"title": str(cite.get("title") or ""), "url": str(cite.get("url") or "")}
                        for cite in item_payload.get("citations", [])
                        if isinstance(cite, dict) and cite.get("url")
                    ],
                }
            )
    await db.execute(
        ConversationShare.__table__.update()
        .where(
            ConversationShare.conversation_id == conversation_id,
            ConversationShare.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    token = secrets.token_urlsafe(24)
    public_id = f"shr_{uuid.uuid4().hex}"
    db.add(
        ConversationShare(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            user_id=current_user.id,
            public_id=public_id,
            token_hash=_share_token_hash(token),
            snapshot={
                "title": session.display_title or session.title or "OpenTrace 对话",
                "messages": messages,
            },
        )
    )
    await db.commit()
    return {"public_id": public_id, "token": token, "url": f"/share/{public_id}/{token}"}


@router.delete("/conversations/{conversation_id}/share")
async def revoke_share(
    conversation_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, _org_id, workspace_id = _scope(request, current_user.id)
    await _owned_session(db, conversation_id, current_user.id, tenant_id, workspace_id)
    result = await db.execute(
        ConversationShare.__table__.update()
        .where(
            ConversationShare.conversation_id == conversation_id,
            ConversationShare.user_id == current_user.id,
            ConversationShare.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()
    return {"revoked": bool(result.rowcount)}


@router.get("/shared/{public_id}/{token}")
async def get_shared_conversation(
    public_id: str,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    share = await db.scalar(
        select(ConversationShare).where(
            ConversationShare.public_id == public_id,
            ConversationShare.revoked_at.is_(None),
        )
    )
    if share is None or not secrets.compare_digest(share.token_hash, _share_token_hash(token)):
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="分享链接无效或已撤销")
    return dict(share.snapshot or {})


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    tenant_id, _org_id, workspace_id = _scope(request, current_user.id)
    session = await _owned_session(db, conversation_id, current_user.id, tenant_id, workspace_id)
    chain = await _active_chain(db, session, current_user.id)
    by_response = await _items_for(db, [row.id for row in chain])
    all_rows = (
        (
            await db.execute(
                select(ResponseRecord)
                .where(
                    ResponseRecord.conversation_id == conversation_id,
                    ResponseRecord.user_id == current_user.id,
                )
                .order_by(ResponseRecord.created_at)
            )
        )
        .scalars()
        .all()
    )
    siblings: dict[str | None, list[ResponseRecord]] = {}
    for row in all_rows:
        siblings.setdefault(row.parent_response_id, []).append(row)
    requested_attachment_ids = {
        str(attachment_id)
        for response in chain
        for attachment_id in (
            (response.request_payload or {}).get("opentrace", {}).get("attachment_ids") or []
        )
    }
    attachment_rows = (
        (
            await db.execute(
                select(Attachment).where(
                    Attachment.id.in_(requested_attachment_ids),
                    Attachment.user_id == current_user.id,
                    Attachment.session_id == conversation_id,
                    Attachment.status == "active",
                )
            )
        )
        .scalars()
        .all()
        if requested_attachment_ids
        else []
    )
    attachments_by_id = {row.id: row for row in attachment_rows}
    messages: list[MessageOut] = []
    for response in chain:
        versions = siblings.get(response.parent_response_id, [])
        version_index = next(
            (index + 1 for index, row in enumerate(versions) if row.id == response.id), 1
        )
        response_attachment_ids = list(
            (response.request_payload or {}).get("opentrace", {}).get("attachment_ids") or []
        )
        response_attachments = [
            {
                "id": row.id,
                "filename": row.filename,
                "file_size": int(row.file_size or 0),
                "file_extension": row.file_extension,
                "mime_type": row.mime_type,
                "content_summary": row.content_summary,
            }
            for attachment_id in response_attachment_ids
            if (row := attachments_by_id.get(str(attachment_id))) is not None
        ]
        pending_approvals = (
            (
                await db.execute(
                    select(ResponseApproval).where(
                        ResponseApproval.response_id == response.id,
                        ResponseApproval.status == "pending",
                    )
                )
            )
            .scalars()
            .all()
            if response.status == "requires_action"
            else []
        )
        approval_payloads = _approval_payloads(list(pending_approvals))
        response_items = by_response.get(response.id, [])
        response_messages: list[MessageOut] = []
        for item in response_items:
            if item.item_type not in {"input_message", "message"}:
                continue
            item_payload = dict(item.payload or {})
            role = item.role or ("user" if item.item_type == "input_message" else "assistant")
            response_messages.append(
                MessageOut(
                    id=item.id,
                    role=role,
                    content=item.content or "",
                    created_at=(
                        item.created_at.isoformat()
                        if item.created_at
                        else response.created_at.isoformat()
                    ),
                    model=response.model,
                    status=response.status,
                    metadata=item_payload,
                    citations=list(item_payload.get("citations") or []),
                    annotations=list(item_payload.get("annotations") or []),
                    response_id=response.id,
                    parent_response_id=response.parent_response_id,
                    version=response.version,
                    version_index=version_index,
                    sibling_count=len(versions),
                    attachments=response_attachments if role == "user" else [],
                )
            )
        messages.extend(
            _project_response_approvals(
                response,
                response_messages,
                approval_payloads,
                version_index=version_index,
                sibling_count=len(versions),
            )
        )
    return messages
