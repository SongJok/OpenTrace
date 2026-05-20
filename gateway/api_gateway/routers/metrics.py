"""
Metrics CRUD API — manage metric_definitions knowledge assets.

Endpoints:
  GET  /api/v1/metrics — list metrics (filter by data_source_id, status, category)
  POST /api/v1/metrics — create new metric definition
  GET  /api/v1/metrics/{metric_id} — get single metric
  PUT  /api/v1/metrics/{metric_id} — update metric
  DELETE /api/v1/metrics/{metric_id} — delete metric
  POST /api/v1/metrics/{metric_id}/publish — publish a draft metric
  POST /api/v1/metrics/{metric_id}/deprecate — deprecate a metric
  GET  /api/v1/metrics/{metric_id}/lineage — get metric lineage graph
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from infra.errors import AppException, ErrorCodes
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import MetricDefinition, MetricLineage, User

router = APIRouter()


# ── Pydantic Schemas ─────────────────────────────────────────────────

class MetricCreateRequest(BaseModel):
    data_source_id: str = Field(..., min_length=1, max_length=36)
    name: str = Field(..., min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    formula: str = Field(..., min_length=1)
    underlying_columns: list[str] = Field(default_factory=list)
    agg_function: str | None = None
    business_definition: str | None = None
    unit: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    sensitivity: str = Field(default="public")


class MetricUpdateRequest(BaseModel):
    name: str | None = None
    aliases: list[str] | None = None
    formula: str | None = None
    underlying_columns: list[str] | None = None
    agg_function: str | None = None
    business_definition: str | None = None
    unit: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    sensitivity: str | None = None


# ── Routes ──────────────────────────────────────────────────────────

@router.get("/metrics")
async def list_metrics(
    data_source_id: str = Query(default=""),
    status: str = Query(default=""),
    category: str = Query(default=""),
    search: str = Query(default=""),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List metric definitions with optional filtering."""
    conditions = []
    if data_source_id:
        conditions.append(MetricDefinition.data_source_id == data_source_id)
    if status:
        conditions.append(MetricDefinition.status == status)
    if category:
        conditions.append(MetricDefinition.category == category)
    if search:
        conditions.append(MetricDefinition.name.ilike(f"%{search}%"))

    from sqlalchemy import and_
    query = select(MetricDefinition)
    if conditions:
        query = query.where(and_(*conditions))
    query = query.order_by(MetricDefinition.updated_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "items": [_metric_to_dict(m) for m in items],
        "total": len(items),
        "limit": limit,
        "offset": offset,
    }


@router.get("/metrics/{metric_id}")
async def get_metric(
    metric_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single metric definition."""
    result = await db.execute(
        select(MetricDefinition).where(MetricDefinition.id == metric_id)
    )
    metric = result.scalar()
    if not metric:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="metric not found")
    return {"metric": _metric_to_dict(metric)}


@router.post("/metrics")
async def create_metric(
    req: MetricCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new metric definition."""
    metric = MetricDefinition(
        data_source_id=req.data_source_id,
        name=req.name,
        aliases=req.aliases,
        formula=req.formula,
        underlying_columns=req.underlying_columns,
        agg_function=req.agg_function,
        business_definition=req.business_definition,
        unit=req.unit,
        category=req.category,
        tags=req.tags,
        sensitivity=req.sensitivity,
        status="draft",
        version=1,
        created_by=current_user.id,
    )
    db.add(metric)
    await db.commit()
    await db.refresh(metric)
    return {"metric": _metric_to_dict(metric)}


@router.put("/metrics/{metric_id}")
async def update_metric(
    metric_id: str,
    req: MetricUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update a metric definition. Creates a new draft version if published."""
    result = await db.execute(
        select(MetricDefinition).where(MetricDefinition.id == metric_id)
    )
    existing = result.scalar()
    if not existing:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="metric not found")

    update_data = req.dict(exclude_unset=True, exclude_none=True)

    if existing.status == "published" and update_data:
        # Create new draft version instead of mutating published metric
        new_version = (existing.version or 1) + 1
        metric = MetricDefinition(
            data_source_id=existing.data_source_id,
            name=update_data.get("name", existing.name),
            aliases=update_data.get("aliases", existing.aliases),
            formula=update_data.get("formula", existing.formula),
            underlying_columns=update_data.get("underlying_columns", existing.underlying_columns),
            agg_function=update_data.get("agg_function", existing.agg_function),
            business_definition=update_data.get("business_definition", existing.business_definition),
            unit=update_data.get("unit", existing.unit),
            category=update_data.get("category", existing.category),
            tags=update_data.get("tags", existing.tags),
            sensitivity=update_data.get("sensitivity", existing.sensitivity),
            status="draft",
            version=new_version,
            created_by=current_user.id,
        )
        db.add(metric)
        await db.flush()

        # Record lineage
        lineage = MetricLineage(
            metric_id=metric.id,
            depends_on_metric_id=metric_id,
            transformation=f"New version from v{existing.version}",
            lineage_type="derived",
        )
        db.add(lineage)
        await db.commit()
        await db.refresh(metric)
        return {"metric": _metric_to_dict(metric), "versioned": True}

    # Draft or deprecated: update in-place
    for key, val in update_data.items():
        setattr(existing, key, val)
    await db.commit()
    await db.refresh(existing)
    return {"metric": _metric_to_dict(existing), "versioned": False}


@router.delete("/metrics/{metric_id}")
async def delete_metric(
    metric_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a metric definition."""
    result = await db.execute(
        select(MetricDefinition).where(MetricDefinition.id == metric_id)
    )
    metric = result.scalar()
    if not metric:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="metric not found")
    await db.delete(metric)
    await db.commit()
    return {"deleted": True, "metric_id": metric_id}


@router.post("/metrics/{metric_id}/publish")
async def publish_metric(
    metric_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Publish a draft metric definition."""
    result = await db.execute(
        select(MetricDefinition).where(MetricDefinition.id == metric_id)
    )
    metric = result.scalar()
    if not metric:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="metric not found")
    if metric.status != "draft":
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="only draft metrics can be published")

    from datetime import datetime, timezone
    metric.status = "published"
    metric.approved_by = current_user.id
    metric.approved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(metric)
    return {"metric": _metric_to_dict(metric)}


@router.post("/metrics/{metric_id}/deprecate")
async def deprecate_metric(
    metric_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deprecate a metric definition."""
    result = await db.execute(
        select(MetricDefinition).where(MetricDefinition.id == metric_id)
    )
    metric = result.scalar()
    if not metric:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="metric not found")

    metric.status = "deprecated"
    await db.commit()
    await db.refresh(metric)
    return {"metric": _metric_to_dict(metric)}


@router.get("/metrics/{metric_id}/lineage")
async def get_metric_lineage(
    metric_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get the lineage graph for a metric."""
    result = await db.execute(
        select(MetricLineage).where(
            (MetricLineage.metric_id == metric_id)
            | (MetricLineage.depends_on_metric_id == metric_id)
        )
    )
    edges = result.scalars().all()
    return {
        "metric_id": metric_id,
        "lineage": [
            {
                "id": e.id,
                "metric_id": e.metric_id,
                "depends_on_metric_id": e.depends_on_metric_id,
                "depends_on_column": e.depends_on_column,
                "transformation": e.transformation,
                "lineage_type": e.lineage_type,
            }
            for e in edges
        ],
    }


def _metric_to_dict(m: MetricDefinition) -> dict:
    return {
        "id": m.id,
        "data_source_id": m.data_source_id,
        "name": m.name,
        "aliases": m.aliases,
        "formula": m.formula,
        "underlying_columns": m.underlying_columns,
        "agg_function": m.agg_function,
        "business_definition": m.business_definition,
        "unit": m.unit,
        "category": m.category,
        "tags": m.tags,
        "sensitivity": m.sensitivity,
        "version": m.version,
        "status": m.status,
        "approved_by": m.approved_by,
        "approved_at": str(m.approved_at) if m.approved_at else None,
        "created_by": m.created_by,
        "created_at": str(m.created_at) if m.created_at else None,
        "updated_at": str(m.updated_at) if m.updated_at else None,
    }
