from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import get_accessible_data_source
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import DataSourceSchema, User
from services.sql_assets import generate_sql_query_draft, serialize_draft

router = APIRouter()


class DataQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=8192)
    data_source_id: str
    # 保留旧客户端字段用于请求兼容，但公开入口始终只生成草案。
    dry_run: bool = False
    sql: str | None = None
    limit: int | None = Field(default=None, ge=1, le=500)
    offset: int | None = Field(default=None, ge=0)
    order_by: str | None = None
    order_dir: str | None = Field(default=None, pattern="^(asc|desc)$")
    filters: list[dict[str, object]] | None = None
    session_id: str | None = None
    clarify_context: str | None = None
    session_context: dict[str, object] | None = None
    group_type: str = Field(default="alternative", pattern="^(alternative|batch)$")
    project_id: str | None = None


@router.post("/data/query")
async def data_query(
    req: DataQueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    http_request: Request = None,
) -> dict:
    """公开问数入口只生成持久化 SQL 草案，不接受客户端绕过确认。"""

    tenant_md = (
        build_tenant_metadata(http_request, user_id=current_user.id)
        if http_request is not None
        else {"tenant_id": "default", "workspace_id": "default"}
    )
    source = await get_accessible_data_source(
        db,
        user_id=current_user.id,
        tenant_metadata=tenant_md,
        data_source_id=req.data_source_id,
        required_permission="query",
        active_only=True,
    )
    if source is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="data source not found")
    draft, candidates = await generate_sql_query_draft(
        db,
        user_id=current_user.id,
        tenant_id=str(tenant_md.get("tenant_id") or "default"),
        workspace_id=str(tenant_md.get("workspace_id") or "default"),
        data_source=source,
        question=req.question,
        supplied_sql=req.sql,
        project_id=req.project_id,
        conversation_id=req.session_id,
        group_type=req.group_type,
    )
    payload = serialize_draft(draft, candidates)
    return {
        "data_source_id": req.data_source_id,
        "answer": "SQL 草案已生成，尚未执行。请选择具体方案或执行全部方案。",
        "summary": f"已生成 {len(candidates)} 条只读 SQL 候选，等待确认执行",
        "sql": candidates[0].sql if candidates else "",
        "rows": [],
        "confidence": 0.9,
        "mode": "sql_draft",
        "draft": payload,
        "draft_id": draft.id,
        "candidates": payload["candidates"],
        "executed": False,
    }


class DataSchemaSyncRequest(BaseModel):
    data_source_id: str


@router.post("/data/schema/sync")
async def data_schema_sync(
    http_request: Request,
    req: DataSchemaSyncRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from gateway.api_gateway.routers.databases import sync_schema as databases_sync_schema

    return await databases_sync_schema(
        database_id=req.data_source_id,
        current_user=current_user,
        db=db,
        http_request=http_request,
    )


@router.get("/data/schema")
async def data_schema(
    http_request: Request,
    data_source_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_md = build_tenant_metadata(http_request, user_id=current_user.id)
    source = await get_accessible_data_source(
        db,
        user_id=current_user.id,
        tenant_metadata=tenant_md,
        data_source_id=data_source_id,
        required_permission="view",
    )
    if source is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="data source not found")

    rs = await db.execute(
        select(DataSourceSchema).where(DataSourceSchema.data_source_id == data_source_id)
    )
    schema_row = rs.scalar_one_or_none()
    if schema_row is None:
        return {"data_source_id": data_source_id, "schema": {"tables": []}, "synced": False}

    payload = json.loads(schema_row.schema_json or "{}")
    return {"data_source_id": data_source_id, "schema": payload, "synced": True}
