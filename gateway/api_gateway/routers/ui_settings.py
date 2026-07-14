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
    dag_default_expanded: bool = True
    execution_graph_default_expanded: bool = True
    decision_trace_default_expanded: bool = True
    flow_cards_default_expanded: bool = True
    theme_mode: str = "system"
    theme_accent: str = "blue"


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
        dag_default_expanded=bool(row.dag_default_expanded),
        execution_graph_default_expanded=bool(row.execution_graph_default_expanded),
        decision_trace_default_expanded=bool(row.decision_trace_default_expanded),
        flow_cards_default_expanded=bool(row.flow_cards_default_expanded),
        theme_mode=row.theme_mode,
        theme_accent=row.theme_accent,
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
            dag_default_expanded=req.dag_default_expanded,
            execution_graph_default_expanded=req.execution_graph_default_expanded,
            decision_trace_default_expanded=req.decision_trace_default_expanded,
            flow_cards_default_expanded=req.flow_cards_default_expanded,
            theme_mode=req.theme_mode,
            theme_accent=req.theme_accent,
        )
        db.add(row)
    else:
        row.reasoning_default_expanded = req.reasoning_default_expanded
        row.graph_default_expanded = req.graph_default_expanded
        row.dag_default_expanded = req.dag_default_expanded
        row.execution_graph_default_expanded = req.execution_graph_default_expanded
        row.decision_trace_default_expanded = req.decision_trace_default_expanded
        row.flow_cards_default_expanded = req.flow_cards_default_expanded
        row.theme_mode = req.theme_mode
        row.theme_accent = req.theme_accent
    await db.commit()
    return UiSettingsPayload(
        reasoning_default_expanded=bool(req.reasoning_default_expanded),
        graph_default_expanded=bool(req.graph_default_expanded),
        dag_default_expanded=bool(req.dag_default_expanded),
        execution_graph_default_expanded=bool(req.execution_graph_default_expanded),
        decision_trace_default_expanded=bool(req.decision_trace_default_expanded),
        flow_cards_default_expanded=bool(req.flow_cards_default_expanded),
        theme_mode=req.theme_mode,
        theme_accent=req.theme_accent,
    )
