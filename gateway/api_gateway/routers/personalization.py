"""Explicit personalization controls: custom instructions, not learned memory."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import normalized_tenant_scope
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import User, UserCustomInstruction

router = APIRouter()


class CustomInstructionPayload(BaseModel):
    about_user: str = Field(default="", max_length=4000)
    response_style: str = Field(default="", max_length=4000)
    enabled: bool = True


def _serialize(row: UserCustomInstruction | None) -> dict[str, Any]:
    if row is None:
        return {"about_user": "", "response_style": "", "enabled": True, "version": 0}
    return {
        "id": row.id,
        "about_user": row.about_user,
        "response_style": row.response_style,
        "enabled": bool(row.enabled),
        "version": row.version,
        "tenant_id": row.tenant_id,
        "workspace_id": row.workspace_id,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/personalization/custom-instructions")
async def get_custom_instructions(
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(http_request, user_id=current_user.id)
    )
    row = (
        await db.execute(
            select(UserCustomInstruction).where(
                UserCustomInstruction.user_id == current_user.id,
                UserCustomInstruction.tenant_id == tenant_id,
                UserCustomInstruction.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    return _serialize(row)


@router.put("/personalization/custom-instructions")
async def set_custom_instructions(
    http_request: Request,
    req: CustomInstructionPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(http_request, user_id=current_user.id)
    )
    row = (
        await db.execute(
            select(UserCustomInstruction).where(
                UserCustomInstruction.user_id == current_user.id,
                UserCustomInstruction.tenant_id == tenant_id,
                UserCustomInstruction.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = UserCustomInstruction(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        db.add(row)
    row.about_user = req.about_user.strip()
    row.response_style = req.response_style.strip()
    row.enabled = req.enabled
    row.version = int(row.version or 0) + 1
    await db.commit()
    await db.refresh(row)
    return _serialize(row)


@router.delete("/personalization/custom-instructions")
async def delete_custom_instructions(
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(http_request, user_id=current_user.id)
    )
    row = (
        await db.execute(
            select(UserCustomInstruction).where(
                UserCustomInstruction.user_id == current_user.id,
                UserCustomInstruction.tenant_id == tenant_id,
                UserCustomInstruction.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {"deleted": False}
    await db.delete(row)
    await db.commit()
    return {"deleted": True}
