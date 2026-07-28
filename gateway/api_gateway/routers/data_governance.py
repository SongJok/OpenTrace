"""企业数据治理管理 API。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.admin import get_current_admin_user
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import DataDeletionJob, LegalHold, User
from services.data_governance import create_legal_hold, request_tenant_deletion

router = APIRouter()


class LegalHoldCreate(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(default="*", min_length=1, max_length=128)
    resource_type: str = Field(default="tenant", min_length=1, max_length=64)
    resource_id: str | None = Field(default=None, max_length=128)
    reason: str = Field(min_length=3, max_length=2000)
    expires_at: datetime | None = None


class DeletionRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, max_length=128)
    reason: str = Field(min_length=3, max_length=2000)


@router.post("/admin/legal-holds")
async def add_legal_hold(
    request: LegalHoldCreate,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    hold = await create_legal_hold(
        db,
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
        reason=request.reason,
        created_by=admin.id,
        expires_at=request.expires_at,
    )
    await db.commit()
    return {"id": hold.id, "status": hold.status}


@router.post("/admin/data-deletions")
async def request_data_deletion(
    request: DeletionRequest,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    job = await request_tenant_deletion(
        db,
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        requested_by=admin.id,
        reason=request.reason,
    )
    await db.commit()
    return {
        "id": job.id,
        "status": job.status,
        "phase": job.phase,
        "execute_after": job.execute_after.isoformat(),
    }


@router.delete("/admin/legal-holds/{hold_id}")
async def release_legal_hold(
    hold_id: str,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    hold = await db.scalar(
        select(LegalHold).where(LegalHold.id == hold_id, LegalHold.status == "active")
    )
    if hold is None:
        from infra.errors import AppException, ErrorCodes

        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Legal Hold 不存在")
    hold.status = "released"
    hold.released_by = admin.id
    hold.released_at = datetime.now(UTC)
    blocked_jobs = list(
        (
            await db.scalars(
                select(DataDeletionJob).where(
                    DataDeletionJob.tenant_id == hold.tenant_id,
                    DataDeletionJob.status == "blocked",
                )
            )
        ).all()
    )
    for job in blocked_jobs:
        if hold.workspace_id not in {"*", job.workspace_id}:
            continue
        job.status = "pending"
        job.phase = "grace_period"
        job.progress = {}
    await db.commit()
    return {"id": hold.id, "status": hold.status}
