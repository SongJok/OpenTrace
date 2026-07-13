"""Auxiliary resources for the Responses surface."""

from __future__ import annotations

from datetime import UTC, datetime
import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import ResponseEvent, ResponseRecord, ResponseToolExecution, User

router = APIRouter()


@router.post("/responses/{response_id}/tool-approvals")
async def approve_response_tool(
    response_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve/reject a side-effecting tool call and append an auditable event.

    The endpoint is intentionally idempotent: repeating the same decision
    returns the existing ledger row and never executes a tool twice.
    """
    call_id = str(payload.get("call_id") or "")
    if not call_id:
        return {"approved": False, "error": "call_id is required"}
    response = await db.scalar(
        select(ResponseRecord).where(ResponseRecord.id == response_id, ResponseRecord.user_id == current_user.id)
    )
    if response is None:
        return {"approved": False, "error": "response not found"}
    tool = await db.scalar(
        select(ResponseToolExecution).where(
            ResponseToolExecution.response_id == response_id,
            ResponseToolExecution.call_id == call_id,
        )
    )
    if tool is None:
        return {"approved": False, "error": "tool call not found"}
    approved = bool(payload.get("approved", False))
    if tool.status in {"approved", "rejected", "completed"}:
        return {"approved": tool.status in {"approved", "completed"}, "status": tool.status, "call_id": call_id}
    tool.status = "approved" if approved else "rejected"
    tool.error_message = None if approved else str(payload.get("reason") or "user rejected tool call")
    event_seq = await db.scalar(
        select(ResponseEvent.sequence_number)
        .where(ResponseEvent.response_id == response_id)
        .order_by(ResponseEvent.sequence_number.desc())
        .limit(1)
    )
    db.add(
        ResponseEvent(
            id=f"evt_{uuid.uuid4().hex}",
            response_id=response_id,
            sequence_number=(int(event_seq) if event_seq is not None else -1) + 1,
            event_type="response.tool_approval",
            payload={"call_id": call_id, "approved": approved, "status": tool.status},
            created_at=datetime.now(UTC),
        )
    )
    await db.commit()
    return {"approved": approved, "status": tool.status, "call_id": call_id}


@router.post("/files")
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    message_id: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from gateway.api_gateway.routers.chat import upload_attachment

    return await upload_attachment(file, session_id, message_id, current_user, db)


@router.get("/files/{session_id}")
async def list_files(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from gateway.api_gateway.routers.chat import list_attachments

    return await list_attachments(session_id, current_user, db)


@router.post("/files/{file_id}/promote")
async def promote_file(
    request: Request,
    file_id: str,
    publish_policy: str = "review",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from gateway.api_gateway.routers.chat import promote_chat_attachment

    return await promote_chat_attachment(request, file_id, publish_policy, current_user, db)


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from gateway.api_gateway.routers.chat import delete_attachment

    return await delete_attachment(file_id, current_user, db)


@router.get("/messages/{message_id}/versions")
async def message_versions(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from gateway.api_gateway.routers.chat import get_message_versions

    return await get_message_versions(message_id, current_user, db)


@router.post("/responses/{response_id}/feedback")
async def response_feedback(
    response_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from gateway.api_gateway.routers.chat import ChatFeedbackRequest, chat_feedback

    request = ChatFeedbackRequest(
        session_id=str(payload.get("session_id") or ""),
        message_id=str(payload.get("message_id") or response_id),
        feedback_type=str(payload.get("feedback_type") or "none"),
        score=payload.get("score"),
        correction=payload.get("correction"),
    )
    return await chat_feedback(request, current_user, db)
