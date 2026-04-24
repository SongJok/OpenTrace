from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from infra.errors import AppException, ErrorCodes
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import User, UserMemory, UserMemorySettings

router = APIRouter()


class MemoryCreateRequest(BaseModel):
    memory_type: str = Field(..., pattern="^(semantic|episodic|procedural)$")
    kind: str = Field(default="fact")
    title: Optional[str] = None
    content: str = Field(..., min_length=1, max_length=10000)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    pinned: bool = False


class MemoryUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None
    pinned: Optional[bool] = None


class MemorySettingsRequest(BaseModel):
    memory_learning_enabled: bool = True
    preference_learning_enabled: bool = True


@router.get("/memories")
async def list_memories(
    memory_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    q = select(UserMemory).where(UserMemory.user_id == current_user.id)
    if memory_type:
        q = q.where(UserMemory.memory_type == memory_type)
    q = q.order_by(UserMemory.pinned.desc(), UserMemory.updated_at.desc())
    r = await db.execute(q)
    items = r.scalars().all()
    return {
        "items": [
            {
                "id": m.id,
                "memory_type": m.memory_type,
                "kind": m.kind,
                "title": m.title,
                "content": m.content,
                "tags": json.loads(m.tags_json or "[]"),
                "metadata": json.loads(m.metadata_json or "{}"),
                "enabled": m.enabled,
                "pinned": m.pinned,
                "access_count": m.access_count,
                "last_accessed_at": m.last_accessed_at.isoformat() if m.last_accessed_at else None,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in items
        ]
    }


@router.post("/memories")
async def create_memory(
    req: MemoryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    m = UserMemory(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        memory_type=req.memory_type,
        kind=req.kind,
        title=req.title,
        content=req.content,
        tags_json=json.dumps(req.tags, ensure_ascii=False),
        metadata_json=json.dumps(req.metadata, ensure_ascii=False),
        enabled=req.enabled,
        pinned=req.pinned,
    )
    db.add(m)
    await db.commit()
    return {"id": m.id, "created": True}


@router.patch("/memories/{memory_id}")
async def update_memory(
    memory_id: str,
    req: MemoryUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    r = await db.execute(select(UserMemory).where(UserMemory.id == memory_id, UserMemory.user_id == current_user.id))
    m = r.scalar_one_or_none()
    if m is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="memory not found")

    if req.title is not None:
        m.title = req.title
    if req.content is not None:
        m.content = req.content
    if req.tags is not None:
        m.tags_json = json.dumps(req.tags, ensure_ascii=False)
    if req.metadata is not None:
        m.metadata_json = json.dumps(req.metadata, ensure_ascii=False)
    if req.enabled is not None:
        m.enabled = req.enabled
    if req.pinned is not None:
        m.pinned = req.pinned

    await db.commit()
    return {"updated": True}


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    r = await db.execute(select(UserMemory).where(UserMemory.id == memory_id, UserMemory.user_id == current_user.id))
    m = r.scalar_one_or_none()
    if m is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="memory not found")
    await db.delete(m)
    await db.commit()
    return {"deleted": True}


@router.get("/memories/settings")
async def get_memory_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    r = await db.execute(select(UserMemorySettings).where(UserMemorySettings.user_id == current_user.id))
    s = r.scalar_one_or_none()
    if s is None:
        return {"memory_learning_enabled": True, "preference_learning_enabled": True}
    return {
        "memory_learning_enabled": s.memory_learning_enabled,
        "preference_learning_enabled": s.preference_learning_enabled,
    }


@router.post("/memories/settings")
async def set_memory_settings(
    req: MemorySettingsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    r = await db.execute(select(UserMemorySettings).where(UserMemorySettings.user_id == current_user.id))
    s = r.scalar_one_or_none()
    if s is None:
        s = UserMemorySettings(id=str(uuid.uuid4()), user_id=current_user.id)
        db.add(s)
    s.memory_learning_enabled = req.memory_learning_enabled
    s.preference_learning_enabled = req.preference_learning_enabled
    s.updated_at = datetime.utcnow()
    await db.commit()
    return {
        "memory_learning_enabled": s.memory_learning_enabled,
        "preference_learning_enabled": s.preference_learning_enabled,
    }
