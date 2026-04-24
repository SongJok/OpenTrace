from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import User, UserUiSettings

router = APIRouter()


class UiSettingsPayload(BaseModel):
    reasoning_default_expanded: bool = True
    graph_default_expanded: bool = True


@router.get('/users/ui-settings')
async def get_ui_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UiSettingsPayload:
    result = await db.execute(select(UserUiSettings).where(UserUiSettings.user_id == current_user.id))
    row = result.scalar_one_or_none()
    if not row:
        return UiSettingsPayload()
    return UiSettingsPayload(
        reasoning_default_expanded=bool(row.reasoning_default_expanded),
        graph_default_expanded=bool(row.graph_default_expanded),
    )


@router.patch('/users/ui-settings')
async def patch_ui_settings(
    req: UiSettingsPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UiSettingsPayload:
    result = await db.execute(select(UserUiSettings).where(UserUiSettings.user_id == current_user.id))
    row = result.scalar_one_or_none()
    if not row:
        row = UserUiSettings(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            reasoning_default_expanded=req.reasoning_default_expanded,
            graph_default_expanded=req.graph_default_expanded,
        )
        db.add(row)
    else:
        row.reasoning_default_expanded = req.reasoning_default_expanded
        row.graph_default_expanded = req.graph_default_expanded
    await db.commit()
    return UiSettingsPayload(
        reasoning_default_expanded=bool(req.reasoning_default_expanded),
        graph_default_expanded=bool(req.graph_default_expanded),
    )
