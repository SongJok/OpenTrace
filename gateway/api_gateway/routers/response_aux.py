"""Auxiliary resources for the Responses surface."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.responses.repository import add_outbox, append_event
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    Feedback,
    ResponseApproval,
    ResponseItem,
    ResponseRecord,
    ResponseToolExecution,
    User,
)

router = APIRouter()


def _scope(request: Request, user: User) -> tuple[str, str]:
    metadata = build_tenant_metadata(request, user_id=user.id)
    return str(metadata.get("tenant_id") or "default"), str(metadata.get("workspace_id") or "default")


async def _owned_response(
    db: AsyncSession,
    *,
    response_id: str,
    user: User,
    request: Request,
) -> ResponseRecord | None:
    tenant_id, workspace_id = _scope(request, user)
    return await db.scalar(
        select(ResponseRecord).where(
            ResponseRecord.id == response_id,
            ResponseRecord.user_id == user.id,
            ResponseRecord.tenant_id == tenant_id,
            ResponseRecord.workspace_id == workspace_id,
        )
    )


@router.post("/responses/{response_id}/tool-approvals")
async def approve_response_tool(
    response_id: str,
    request: Request,
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
    response = await _owned_response(db, response_id=response_id, user=current_user, request=request)
    if response is None:
        return {"approved": False, "error": "response not found"}
    approval = await db.scalar(
        select(ResponseApproval).where(
            ResponseApproval.response_id == response_id,
            ResponseApproval.call_id == call_id,
        )
    )
    if approval is None:
        return {"approved": False, "error": "tool call not found"}
    approved = bool(payload.get("approved", False))
    if approval.status in {"approved", "rejected"}:
        return {"approved": approval.status == "approved", "status": approval.status, "call_id": call_id}
    approval.status = "approved" if approved else "rejected"
    approval.reason = None if approved else str(payload.get("reason") or "user rejected tool call")
    approval.resolved_by = current_user.id
    approval.resolved_at = datetime.now(UTC)
    tool = await db.scalar(select(ResponseToolExecution).where(ResponseToolExecution.response_id == response_id, ResponseToolExecution.call_id == call_id))
    if tool:
        tool.status = approval.status
        tool.error_message = approval.reason
    await append_event(
        db, response_id=response_id, event_type="opentrace.approval.resolved",
        payload={"approval_id": approval.id, "call_id": call_id, "approved": approved, "status": approval.status},
    )
    if approved:
        response.status = "queued"
        add_outbox(db, response_id=response_id, suffix=f"approval-{approval.id}")
    else:
        response.status = "cancelled"
        response.completed_at = datetime.now(UTC)
        await append_event(db, response_id=response_id, event_type="response.cancelled", payload={"status": "cancelled", "reason": "tool_rejected"})
    await db.commit()
    return {"approved": approved, "status": approval.status, "call_id": call_id, "approval_id": approval.id}


@router.post("/responses/{response_id}/approvals/{approval_id}/resolve")
async def resolve_response_approval(
    response_id: str,
    approval_id: str,
    request: Request,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    response = await _owned_response(db, response_id=response_id, user=current_user, request=request)
    if response is None:
        return {"approved": False, "error": "response not found"}
    approval = await db.scalar(
        select(ResponseApproval).where(
            ResponseApproval.id == approval_id,
            ResponseApproval.response_id == response_id,
        )
    )
    if approval is None:
        return {"approved": False, "error": "approval not found"}
    return await approve_response_tool(
        response_id,
        request,
        {**payload, "call_id": approval.call_id},
        current_user,
        db,
    )


@router.get("/messages/{message_id}/versions")
async def message_versions(
    message_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await db.scalar(select(ResponseItem).where(ResponseItem.id == message_id))
    response_id = item.response_id if item else message_id
    response = await _owned_response(db, response_id=response_id, user=current_user, request=request)
    if response is None:
        return []
    siblings = (
        await db.execute(
            select(ResponseRecord)
            .where(
                ResponseRecord.conversation_id == response.conversation_id,
                ResponseRecord.parent_response_id == response.parent_response_id,
                ResponseRecord.user_id == current_user.id,
                ResponseRecord.tenant_id == response.tenant_id,
                ResponseRecord.workspace_id == response.workspace_id,
            )
            .order_by(ResponseRecord.created_at)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "response_id": row.id,
            "status": row.status,
            "model": row.model,
            "active": row.id == response.id,
            "created_at": row.created_at.isoformat(),
        }
        for row in siblings
    ]


@router.post("/responses/{response_id}/feedback")
async def response_feedback(
    response_id: str,
    request: Request,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await db.scalar(select(ResponseItem).where(ResponseItem.id == response_id))
    canonical_id = item.response_id if item else response_id
    response = await _owned_response(db, response_id=canonical_id, user=current_user, request=request)
    if response is None:
        return {"status": "not_found"}
    response_items = (
        await db.execute(
            select(ResponseItem)
            .where(ResponseItem.response_id == response.id)
            .order_by(ResponseItem.sequence_number)
        )
    ).scalars().all()
    query = next((row.content or "" for row in response_items if row.item_type == "input_message"), "")
    answer = next((row.content or "" for row in reversed(response_items) if row.item_type == "message"), "")
    db.add(
        Feedback(
            id=str(uuid.uuid4()),
            session_id=response.conversation_id,
            query=query,
            response=answer,
            feedback_type=str(payload.get("feedback_type") or "none"),
            score=payload.get("score"),
            correction=payload.get("correction"),
            feedback_metadata=json.dumps(
                {"source": "responses_api", "response_id": response.id, "user_id": current_user.id},
                ensure_ascii=False,
            ),
        )
    )
    await db.commit()
    return {"status": "accepted", "response_id": response.id}
