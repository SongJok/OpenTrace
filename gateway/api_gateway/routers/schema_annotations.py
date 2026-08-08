"""数据源 Schema 业务标注与自动建议审核 API。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import get_accessible_data_source
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.config.settings import settings
from infra.errors import AppException, ErrorCodes, ValidationException
from infra.metadata.schema_inspector import load_schema_inspection
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import SchemaMetadata, SchemaTableMetadata, User
from services.schema_annotations import (
    ANNOTATION_STATUSES,
    approve_annotation,
    reconcile_schema_annotations,
    reject_annotation,
    serialize_annotation,
)
from services.sql_assets import schema_fingerprint

router = APIRouter()


async def _require_source(
    db: AsyncSession,
    request: Request,
    current_user: User,
    database_id: str,
    permission: str,
):
    tenant = build_tenant_metadata(request, user_id=current_user.id)
    source = await get_accessible_data_source(
        db,
        user_id=current_user.id,
        tenant_metadata=tenant,
        data_source_id=database_id,
        required_permission=permission,
    )
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="数据源不存在")
    return source


class SchemaAnnotationUpsertRequest(BaseModel):
    target_type: Literal["table", "column"]
    table_name: str = Field(..., min_length=1, max_length=255)
    column_name: str | None = Field(default=None, max_length=255)
    business_name: str | None = Field(default=None, max_length=255)
    business_description: str | None = Field(default=None, max_length=4000)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=50)
    semantic_type: str | None = Field(default=None, max_length=100)
    value_map: dict[str, Any] = Field(default_factory=dict)
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_time_column: bool = False
    time_grain: str | None = Field(default=None, max_length=20)
    is_metric_column: bool = False
    is_dimension_column: bool = False
    is_sensitive: bool = False
    masking_rule: str | None = Field(default=None, max_length=50)
    lifecycle_stage: str | None = Field(default=None, max_length=50)

    @field_validator("aliases", "tags")
    @classmethod
    def validate_short_labels(cls, values: list[str]) -> list[str]:
        if any(len(value.strip()) > 100 for value in values):
            raise ValueError("别名和标签的单项长度不能超过 100")
        return values

    @model_validator(mode="after")
    def validate_target(self):
        if self.target_type == "column" and not str(self.column_name or "").strip():
            raise ValueError("列标注必须提供 column_name")
        if self.target_type == "table" and self.column_name:
            raise ValueError("表标注不能提供 column_name")
        if len(self.value_map) > 200 or any(
            len(str(key)) > 200 or len(str(value)) > 500 for key, value in self.value_map.items()
        ):
            raise ValueError("枚举映射最多 200 项，键和值长度必须受限")
        return self


class SchemaAnnotationReviewRequest(BaseModel):
    target_type: Literal["table", "column"]
    annotation_id: str = Field(..., min_length=1, max_length=36)
    action: Literal["accept", "reject"]


async def _validate_physical_target(
    db: AsyncSession,
    *,
    data_source_id: str,
    target_type: str,
    table_name: str,
    column_name: str | None,
) -> None:
    inspection = await load_schema_inspection(db, data_source_id)
    if table_name not in inspection.column_map:
        raise ValidationException(f"当前 Schema 中不存在表：{table_name}")
    if target_type == "column" and str(column_name) not in set(
        inspection.column_map.get(table_name, [])
    ):
        raise ValidationException(f"当前 Schema 中不存在列：{table_name}.{column_name}")


@router.get("/databases/{database_id}/schema-annotations")
async def list_schema_annotations(
    request: Request,
    database_id: str,
    status: str | None = Query(default=None),
    search: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=250, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _require_source(db, request, current_user, database_id, "view")
    if status and status not in ANNOTATION_STATUSES:
        raise ValidationException("标注状态无效")

    table_query = select(SchemaTableMetadata).where(
        SchemaTableMetadata.data_source_id == database_id
    )
    column_query = select(SchemaMetadata).where(SchemaMetadata.data_source_id == database_id)
    if status:
        table_query = table_query.where(SchemaTableMetadata.annotation_status == status)
        column_query = column_query.where(SchemaMetadata.annotation_status == status)
    if search.strip():
        pattern = f"%{search.strip()}%"
        table_query = table_query.where(
            or_(
                SchemaTableMetadata.table_name.ilike(pattern),
                SchemaTableMetadata.business_name.ilike(pattern),
                SchemaTableMetadata.business_description.ilike(pattern),
            )
        )
        column_query = column_query.where(
            or_(
                SchemaMetadata.table_name.ilike(pattern),
                SchemaMetadata.column_name.ilike(pattern),
                SchemaMetadata.business_name.ilike(pattern),
                SchemaMetadata.business_description.ilike(pattern),
            )
        )
    tables = list(
        (
            await db.execute(
                table_query.order_by(
                    SchemaTableMetadata.table_name, SchemaTableMetadata.updated_at.desc()
                )
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    columns = list(
        (
            await db.execute(
                column_query.order_by(
                    SchemaMetadata.table_name,
                    SchemaMetadata.column_name,
                    SchemaMetadata.updated_at.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "data_source_id": database_id,
        "tables": [serialize_annotation(item, target_type="table") for item in tables],
        "columns": [serialize_annotation(item, target_type="column") for item in columns],
        "suggested_count": sum(
            item.annotation_status == "suggested" for item in [*tables, *columns]
        ),
        "pagination": {
            "offset": offset,
            "limit": limit,
            "has_more": len(tables) == limit or len(columns) == limit,
        },
    }


@router.put("/databases/{database_id}/schema-annotations")
async def upsert_schema_annotation(
    request: Request,
    database_id: str,
    payload: SchemaAnnotationUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _require_source(db, request, current_user, database_id, "edit")
    table_name = payload.table_name.strip()
    column_name = str(payload.column_name or "").strip() or None
    await _validate_physical_target(
        db,
        data_source_id=database_id,
        target_type=payload.target_type,
        table_name=table_name,
        column_name=column_name,
    )

    if payload.target_type == "table":
        record = await db.scalar(
            select(SchemaTableMetadata).where(
                SchemaTableMetadata.data_source_id == database_id,
                SchemaTableMetadata.table_name == table_name,
            )
        )
        if record is None:
            record = SchemaTableMetadata(
                id=str(uuid.uuid4()), data_source_id=database_id, table_name=table_name
            )
            db.add(record)
    else:
        record = await db.scalar(
            select(SchemaMetadata).where(
                SchemaMetadata.data_source_id == database_id,
                SchemaMetadata.table_name == table_name,
                SchemaMetadata.column_name == column_name,
            )
        )
        if record is None:
            record = SchemaMetadata(
                id=str(uuid.uuid4()),
                data_source_id=database_id,
                table_name=table_name,
                column_name=str(column_name),
            )
            db.add(record)

    record.business_name = payload.business_name.strip() if payload.business_name else None
    record.business_description = (
        payload.business_description.strip() if payload.business_description else None
    )
    record.aliases = list(
        dict.fromkeys(value.strip() for value in payload.aliases if value.strip())
    )
    record.tags = list(dict.fromkeys(value.strip() for value in payload.tags if value.strip()))
    if payload.target_type == "column":
        record.semantic_type = payload.semantic_type
        record.value_map = payload.value_map
        record.is_primary_key = payload.is_primary_key
        record.is_foreign_key = payload.is_foreign_key
        record.is_time_column = payload.is_time_column
        record.time_grain = payload.time_grain
        record.is_metric_column = payload.is_metric_column
        record.is_dimension_column = payload.is_dimension_column
        record.is_sensitive = payload.is_sensitive
        record.masking_rule = payload.masking_rule
        record.lifecycle_stage = payload.lifecycle_stage
    record.annotation_source = "manual"
    record.annotation_confidence = 1.0
    record.annotation_status = "verified"
    record.suggested_changes = {}
    record.created_by = record.created_by or current_user.id
    record.approved_by = current_user.id
    record.approved_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(record)
    return {"annotation": serialize_annotation(record, target_type=payload.target_type)}


@router.post("/databases/{database_id}/schema-annotations/auto-suggest")
async def auto_suggest_schema_annotations(
    request: Request,
    database_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _require_source(db, request, current_user, database_id, "edit")
    inspection = await load_schema_inspection(db, database_id)
    stats = await reconcile_schema_annotations(
        db,
        data_source_id=database_id,
        schema_payload=inspection.schema_payload,
        fingerprint=schema_fingerprint(inspection.schema_payload),
        max_items=settings.schema_annotation_auto_suggest_max_items,
    )
    await db.commit()
    return {"data_source_id": database_id, "stats": stats}


@router.post("/databases/{database_id}/schema-annotations/review")
async def review_schema_annotation(
    request: Request,
    database_id: str,
    payload: SchemaAnnotationReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _require_source(db, request, current_user, database_id, "edit")
    model = SchemaTableMetadata if payload.target_type == "table" else SchemaMetadata
    record = await db.scalar(
        select(model).where(model.id == payload.annotation_id, model.data_source_id == database_id)
    )
    if record is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Schema 标注不存在")
    if payload.action == "accept":
        approve_annotation(record, user_id=current_user.id)
    else:
        reject_annotation(record, user_id=current_user.id)
    await db.commit()
    await db.refresh(record)
    return {"annotation": serialize_annotation(record, target_type=payload.target_type)}


@router.delete("/databases/{database_id}/schema-annotations/{target_type}/{annotation_id}")
async def delete_schema_annotation(
    request: Request,
    database_id: str,
    target_type: Literal["table", "column"],
    annotation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _require_source(db, request, current_user, database_id, "edit")
    model = SchemaTableMetadata if target_type == "table" else SchemaMetadata
    record = await db.scalar(
        select(model).where(model.id == annotation_id, model.data_source_id == database_id)
    )
    if record is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Schema 标注不存在")
    await db.delete(record)
    await db.commit()
    return {"deleted": True, "annotation_id": annotation_id}
