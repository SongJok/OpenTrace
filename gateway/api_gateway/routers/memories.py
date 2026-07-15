from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    MemoryCandidate,
    MemoryEvidence,
    User,
    UserMemory,
    UserMemorySettings,
)

router = APIRouter()


def _scope(request: Request, user: User) -> tuple[str, str]:
    metadata = build_tenant_metadata(request, user_id=user.id)
    return str(metadata.get("tenant_id") or "default"), str(metadata.get("workspace_id") or "default")


class MemoryCreateRequest(BaseModel):
    memory_type: str = Field(..., pattern="^(semantic|episodic|procedural)$")
    kind: str = Field(default="fact")
    memory_key: str | None = Field(default=None, max_length=128)
    title: str | None = None
    content: str = Field(..., min_length=1, max_length=10000)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    pinned: bool = False
    scope_type: str = Field(default="user", pattern="^(user|project|conversation)$")
    scope_id: str | None = None


class MemoryUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    enabled: bool | None = None
    pinned: bool | None = None
    status: str | None = Field(default=None, pattern="^(active|pending|superseded|rejected|expired)$")


class MemorySettingsRequest(BaseModel):
    memory_learning_enabled: bool = True
    preference_learning_enabled: bool = True


@router.get("/memories")
async def list_memories(
    request: Request,
    memory_type: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    q = select(UserMemory).where(
        UserMemory.user_id == current_user.id,
        UserMemory.tenant_id == tenant_id,
        UserMemory.workspace_id == workspace_id,
    )
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
                "memory_key": m.memory_key,
                "title": m.title,
                "content": m.content,
                "tags": json.loads(m.tags_json or "[]"),
                "metadata": json.loads(m.metadata_json or "{}"),
                "enabled": m.enabled,
                "pinned": m.pinned,
                "scope_type": m.scope_type,
                "scope_id": m.scope_id,
                "status": m.status,
                "confidence": m.confidence,
                "salience": m.salience,
                "source_response_id": m.source_response_id,
                "supersedes_id": m.supersedes_id,
                "expires_at": m.expires_at.isoformat() if m.expires_at else None,
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
    request: Request,
    req: MemoryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    m = UserMemory(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        memory_type=req.memory_type,
        kind=req.kind,
        memory_key=req.memory_key,
        title=req.title,
        content=req.content,
        tags_json=json.dumps(req.tags, ensure_ascii=False),
        metadata_json=json.dumps(req.metadata, ensure_ascii=False),
        enabled=req.enabled,
        pinned=req.pinned,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
        status="active",
        confidence=1.0,
    )
    db.add(m)
    await db.commit()
    return {"id": m.id, "created": True}


@router.get("/memories/export")
async def export_memories(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    rows = (
        await db.execute(
            select(UserMemory)
            .where(
                UserMemory.user_id == current_user.id,
                UserMemory.tenant_id == tenant_id,
                UserMemory.workspace_id == workspace_id,
            )
            .order_by(UserMemory.created_at)
        )
    ).scalars().all()
    return {
        "version": 1,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "items": [
            {
                "id": row.id,
                "memory_type": row.memory_type,
                "kind": row.kind,
                "memory_key": row.memory_key,
                "title": row.title,
                "content": row.content,
                "scope_type": row.scope_type,
                "scope_id": row.scope_id,
                "status": row.status,
                "confidence": row.confidence,
                "source_response_id": row.source_response_id,
                "supersedes_id": row.supersedes_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


@router.patch("/memories/{memory_id}")
async def update_memory(
    memory_id: str,
    request: Request,
    req: MemoryUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    r = await db.execute(select(UserMemory).where(UserMemory.id == memory_id, UserMemory.user_id == current_user.id, UserMemory.tenant_id == tenant_id, UserMemory.workspace_id == workspace_id))
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
    if req.status is not None:
        m.status = req.status

    await db.commit()
    return {"updated": True}


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    r = await db.execute(select(UserMemory).where(UserMemory.id == memory_id, UserMemory.user_id == current_user.id, UserMemory.tenant_id == tenant_id, UserMemory.workspace_id == workspace_id))
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


@router.get("/memories/inbox")
async def memory_inbox(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    rows = (
        await db.execute(
            select(MemoryCandidate)
            .where(
                MemoryCandidate.user_id == current_user.id,
                MemoryCandidate.tenant_id == tenant_id,
                MemoryCandidate.workspace_id == workspace_id,
                MemoryCandidate.status == "pending",
            )
            .order_by(MemoryCandidate.created_at.desc())
        )
    ).scalars().all()
    evidence_rows = (
        await db.execute(
            select(MemoryEvidence).where(MemoryEvidence.candidate_id.in_([row.id for row in rows]))
        )
    ).scalars().all() if rows else []
    evidence = {row.candidate_id: row for row in evidence_rows}
    return {"items": [
        {
            "id": row.id, "content": row.content, "kind": row.kind,
            "memory_key": row.memory_key,
            "scope_type": row.scope_type, "scope_id": row.scope_id,
            "confidence": row.confidence, "salience": row.salience,
            "status": row.status, "response_id": row.response_id,
            "evidence": {
                "item_id": evidence[row.id].item_id,
                "excerpt": evidence[row.id].excerpt,
            } if row.id in evidence else None,
        }
        for row in rows
    ]}


@router.post("/memories/inbox/{candidate_id}/resolve")
async def resolve_memory_candidate(
    candidate_id: str,
    request: Request,
    payload: dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    candidate = await db.scalar(
        select(MemoryCandidate).where(
            MemoryCandidate.id == candidate_id,
            MemoryCandidate.user_id == current_user.id,
            MemoryCandidate.tenant_id == tenant_id,
            MemoryCandidate.workspace_id == workspace_id,
        )
    )
    if candidate is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="memory candidate not found")
    approved = bool(payload.get("approved", False))
    if candidate.status != "pending":
        return {"id": candidate.id, "status": candidate.status}
    candidate.status = "active" if approved else "rejected"
    if approved:
        content = str(payload.get("content") or candidate.content).strip()
        conflict = None
        if candidate.memory_key:
            conflict = await db.scalar(
                select(UserMemory)
                .where(
                    UserMemory.user_id == current_user.id,
                    UserMemory.tenant_id == tenant_id,
                    UserMemory.workspace_id == workspace_id,
                    UserMemory.scope_type == candidate.scope_type,
                    UserMemory.scope_id == candidate.scope_id,
                    UserMemory.memory_key == candidate.memory_key,
                    UserMemory.status == "active",
                    UserMemory.content != content,
                )
                .order_by(UserMemory.updated_at.desc())
            )
        memory = UserMemory(
            id=str(uuid.uuid4()), user_id=current_user.id, memory_type="semantic",
            tenant_id=tenant_id, workspace_id=workspace_id,
            kind=candidate.kind, title=content[:80], content=content,
            memory_key=candidate.memory_key,
            enabled=True, pinned=False, score=candidate.salience,
            scope_type=candidate.scope_type, scope_id=candidate.scope_id,
            status="active", confidence=candidate.confidence, salience=candidate.salience,
            source_response_id=candidate.response_id,
            supersedes_id=conflict.id if conflict else None,
        )
        db.add(memory)
        await db.flush()
        evidence = await db.scalar(select(MemoryEvidence).where(MemoryEvidence.candidate_id == candidate.id))
        if evidence:
            evidence.memory_id = memory.id
        if conflict:
            conflict.status = "superseded"
            conflict.enabled = False
    else:
        candidate.rejection_reason = str(payload.get("reason") or "user_rejected")
    await db.commit()
    return {"id": candidate.id, "status": candidate.status}


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
