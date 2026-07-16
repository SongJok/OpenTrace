"""Auxiliary resources for the Responses surface."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.config.settings import settings
from infra.errors import AppException, ErrorCodes
from infra.responses.repository import add_outbox, append_event
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    Attachment,
    ChatSession,
    Feedback,
    ResponseApproval,
    ResponseItem,
    ResponseRecord,
    ResponseToolExecution,
    User,
)

router = APIRouter()

_TEXT_EXTENSIONS = {
    ".csv", ".css", ".html", ".js", ".json", ".log", ".md", ".py",
    ".txt", ".ts", ".xml", ".yaml", ".yml",
}
_DOCUMENT_EXTENSIONS = {".docx", ".pdf", ".pptx", ".xlsx"}
_IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}


async def _extract_attachment_text(raw: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            lines: list[str] = []
            for sheet in workbook.worksheets:
                lines.append(f"[工作表: {sheet.title}]")
                for row in sheet.iter_rows(values_only=True):
                    values = [str(value) for value in row if value is not None]
                    if values:
                        lines.append("\t".join(values))
            return "\n".join(lines)
        finally:
            workbook.close()
    if suffix == ".pptx":
        from pptx import Presentation

        presentation = Presentation(io.BytesIO(raw))
        lines = []
        for index, slide in enumerate(presentation.slides, start=1):
            lines.append(f"[幻灯片 {index}]")
            lines.extend(
                str(shape.text).strip()
                for shape in slide.shapes
                if hasattr(shape, "text") and str(shape.text).strip()
            )
        return "\n".join(lines)
    from gateway.api_gateway.routers.documents import _extract_text

    return await _extract_text(raw, filename)


def _attachment_out(row: Attachment) -> dict:
    return {
        "id": row.id,
        "attachment_id": row.id,
        "filename": row.filename,
        "file_size": int(row.file_size or 0),
        "mime_type": row.mime_type,
        "file_extension": row.file_extension,
        "content_summary": row.content_summary,
        "content_hash": row.content_hash,
        "status": row.status,
        "message_id": row.message_id,
        "scope": row.scope,
        "ingest_status": row.ingest_status,
        "promoted_document_id": row.promoted_document_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def _owned_session(
    db: AsyncSession, *, session_id: str, user: User, request: Request
) -> ChatSession:
    tenant_id, workspace_id = _scope(request, user)
    row = await db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
            ChatSession.tenant_id == tenant_id,
            ChatSession.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Conversation 不存在或无权限")
    return row


@router.post("/files")
async def upload_response_file(
    request: Request,
    file: UploadFile = File(...),
    session_id: str = Form(...),
    message_id: str | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _owned_session(db, session_id=session_id, user=current_user, request=request)
    raw = await file.read()
    max_bytes = max(1, int(settings.attachment_max_size_mb)) * 1024 * 1024
    if not raw:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="附件不能为空")
    if len(raw) > max_bytes:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message=f"附件不能超过 {settings.attachment_max_size_mb}MB",
        )
    filename = Path(file.filename or "attachment").name[:512]
    suffix = Path(filename).suffix.lower()
    supported = _TEXT_EXTENSIONS | _DOCUMENT_EXTENSIONS | _IMAGE_EXTENSIONS
    if suffix not in supported:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message="暂不支持该附件格式",
        )
    content_hash = hashlib.sha256(raw).hexdigest()
    duplicate = await db.scalar(
        select(Attachment).where(
            Attachment.session_id == session_id,
            Attachment.user_id == current_user.id,
            Attachment.content_hash == content_hash,
            Attachment.status == "active",
        )
    )

    mime_type = str(file.content_type or "application/octet-stream")[:255]
    is_image = mime_type.startswith("image/")
    if suffix in _IMAGE_EXTENSIONS:
        is_image = True
        mime_type = {
            ".gif": "image/gif",
            ".jpeg": "image/jpeg",
            ".jpg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }[suffix]
    content_text = ""
    if not is_image:
        try:
            content_text = (await _extract_attachment_text(raw, filename)).strip()
        except Exception as exc:
            raise AppException(
                ErrorCodes.PARAM_INVALID.code,
                message="附件无法解析或文件已损坏",
            ) from exc
    summary = content_text[:512] if content_text else (f"图片附件：{filename}" if is_image else f"附件：{filename}")
    row = Attachment(
        id=str(uuid.uuid4()),
        session_id=session_id,
        user_id=current_user.id,
        filename=filename,
        file_size=len(raw),
        mime_type=mime_type,
        file_extension=Path(filename).suffix.lower().lstrip(".")[:20] or None,
        content_hash=content_hash,
        duplicate_of=duplicate.id if duplicate else None,
        content_text=content_text[: max(1, int(settings.attachment_max_chars)) * 8] or None,
        content_summary=summary,
        image_base64=base64.b64encode(raw).decode("ascii") if is_image else None,
        image_mime=mime_type if is_image else None,
        message_id=message_id,
        status="active",
        scope="session",
        ingest_status="ready",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    result = _attachment_out(row)
    result["is_duplicate"] = duplicate is not None
    return result


@router.get("/files/{session_id}")
async def list_response_files(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _owned_session(db, session_id=session_id, user=current_user, request=request)
    rows = (
        await db.execute(
            select(Attachment)
            .where(
                Attachment.session_id == session_id,
                Attachment.user_id == current_user.id,
                Attachment.status == "active",
            )
            .order_by(Attachment.created_at)
        )
    ).scalars().all()
    return {"session_id": session_id, "attachments": [_attachment_out(row) for row in rows], "total": len(rows)}


@router.delete("/files/{attachment_id}")
async def delete_response_file(
    attachment_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.scalar(
        select(Attachment).where(Attachment.id == attachment_id, Attachment.user_id == current_user.id)
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="附件不存在")
    await _owned_session(db, session_id=row.session_id, user=current_user, request=request)
    row.status = "deleted"
    row.image_base64 = None
    row.content_text = None
    await db.commit()
    return {"attachment_id": attachment_id, "status": "deleted"}


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
    resolved_event = await append_event(
        db, response_id=response_id, event_type="opentrace.approval.resolved",
        payload={"approval_id": approval.id, "call_id": call_id, "approved": approved, "status": approval.status},
    )
    # Both decisions resume the manager. Rejections become typed tool results,
    # allowing the assistant to explain alternatives instead of cancelling the turn.
    response.status = "queued"
    response.completed_at = None
    add_outbox(db, response_id=response_id, suffix=f"approval-{approval.id}")
    await db.commit()
    return {
        "approved": approved,
        "status": approval.status,
        "call_id": call_id,
        "approval_id": approval.id,
        "starting_after": resolved_event.sequence_number,
    }


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
