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

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import (
    accessible_data_sources_statement,
    get_accessible_data_source,
)
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import DataSource, MetricDefinition, MetricLineage, User

router = APIRouter()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _validate_effective_interval(valid_from: datetime | None, valid_to: datetime | None) -> None:
    start = _as_utc(valid_from)
    end = _as_utc(valid_to)
    if start is not None and end is not None and end <= start:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message="valid_to must be later than valid_from",
        )


def _intervals_overlap(
    left_from: datetime | None,
    left_to: datetime | None,
    right_from: datetime | None,
    right_to: datetime | None,
) -> bool:
    minimum = datetime.min.replace(tzinfo=UTC)
    maximum = datetime.max.replace(tzinfo=UTC)
    return (_as_utc(left_from) or minimum) < (_as_utc(right_to) or maximum) and (
        _as_utc(right_from) or minimum
    ) < (_as_utc(left_to) or maximum)


def _metric_certification_missing_fields(metric: MetricDefinition) -> list[str]:
    fields = (
        ("formula", metric.formula),
        ("business_definition", metric.business_definition),
        ("underlying_columns", metric.underlying_columns),
        ("agg_function", metric.agg_function),
        ("owner", metric.owner),
        ("business_domain", metric.business_domain),
        ("grain", metric.grain),
        ("evidence_refs", [item for item in metric.evidence_refs or [] if str(item).strip()]),
    )
    missing = [name for name, value in fields if not value or not str(value).strip()]
    grain = str(metric.grain or "").strip().lower()
    if grain not in {"snapshot", "current", "none"} and not str(metric.time_field or "").strip():
        missing.append("time_field")
    return list(dict.fromkeys(missing))


def _scoped_metrics_statement(request: Request, current_user: User):
    tenant_md = build_tenant_metadata(request, user_id=current_user.id)
    accessible_ids = accessible_data_sources_statement(
        user_id=current_user.id,
        tenant_metadata=tenant_md,
        required_permission="view",
    ).with_only_columns(DataSource.id)
    return select(MetricDefinition).where(MetricDefinition.data_source_id.in_(accessible_ids))


async def _require_owned_source(
    db: AsyncSession,
    request: Request,
    current_user: User,
    data_source_id: str,
    required_permission: str = "view",
) -> DataSource:
    tenant_md = build_tenant_metadata(request, user_id=current_user.id)
    source = await get_accessible_data_source(
        db,
        user_id=current_user.id,
        tenant_metadata=tenant_md,
        data_source_id=data_source_id,
        required_permission=required_permission,
    )
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="data source not found")
    return source


# ── Pydantic Schemas ─────────────────────────────────────────────────


class MetricCreateRequest(BaseModel):
    data_source_id: str = Field(..., min_length=1, max_length=36)
    name: str = Field(..., min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    formula: str = Field(..., min_length=1)
    underlying_columns: list[str] = Field(default_factory=list)
    agg_function: str | None = None
    business_definition: str | None = None
    required_filters: list[str] = Field(default_factory=list)
    time_field: str | None = Field(default=None, max_length=255)
    grain: str | None = Field(default=None, max_length=50)
    owner: str | None = Field(default=None, max_length=255)
    business_domain: str | None = Field(default=None, max_length=128)
    unit: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    sensitivity: str = Field(default="public")
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    quality_contract: dict = Field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class MetricUpdateRequest(BaseModel):
    name: str | None = None
    aliases: list[str] | None = None
    formula: str | None = None
    underlying_columns: list[str] | None = None
    agg_function: str | None = None
    business_definition: str | None = None
    required_filters: list[str] | None = None
    time_field: str | None = None
    grain: str | None = None
    owner: str | None = None
    business_domain: str | None = None
    unit: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    sensitivity: str | None = None
    evidence_refs: list[str] | None = None
    quality_contract: dict | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/metrics")
async def list_metrics(
    http_request: Request,
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

    query = _scoped_metrics_statement(http_request, current_user)
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
    http_request: Request,
    metric_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single metric definition."""
    result = await db.execute(
        _scoped_metrics_statement(http_request, current_user).where(
            MetricDefinition.id == metric_id
        )
    )
    metric = result.scalar()
    if not metric:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="metric not found")
    return {"metric": _metric_to_dict(metric)}


@router.post("/metrics")
async def create_metric(
    http_request: Request,
    req: MetricCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new metric definition."""
    await _require_owned_source(db, http_request, current_user, req.data_source_id, "edit")
    _validate_effective_interval(req.valid_from, req.valid_to)
    latest_version = await db.scalar(
        select(func.max(MetricDefinition.version)).where(
            MetricDefinition.data_source_id == req.data_source_id,
            MetricDefinition.name == req.name,
        )
    )
    metric = MetricDefinition(
        data_source_id=req.data_source_id,
        name=req.name,
        aliases=req.aliases,
        formula=req.formula,
        underlying_columns=req.underlying_columns,
        agg_function=req.agg_function,
        business_definition=req.business_definition,
        required_filters=req.required_filters,
        time_field=req.time_field,
        grain=req.grain,
        owner=req.owner,
        business_domain=req.business_domain,
        unit=req.unit,
        category=req.category,
        tags=req.tags,
        sensitivity=req.sensitivity,
        evidence_refs=req.evidence_refs,
        quality_contract=req.quality_contract,
        valid_from=req.valid_from,
        valid_to=req.valid_to,
        status="draft",
        version=int(latest_version or 0) + 1,
        created_by=current_user.id,
    )
    db.add(metric)
    await db.commit()
    await db.refresh(metric)
    return {"metric": _metric_to_dict(metric)}


@router.put("/metrics/{metric_id}")
async def update_metric(
    http_request: Request,
    metric_id: str,
    req: MetricUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update a metric definition. Creates a new draft version if published."""
    result = await db.execute(
        _scoped_metrics_statement(http_request, current_user).where(
            MetricDefinition.id == metric_id
        )
    )
    existing = result.scalar()
    if not existing:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="metric not found")
    await _require_owned_source(db, http_request, current_user, existing.data_source_id, "edit")

    update_data = req.dict(exclude_unset=True, exclude_none=True)
    _validate_effective_interval(
        update_data.get("valid_from", existing.valid_from),
        update_data.get("valid_to", existing.valid_to),
    )

    if existing.status == "published" and update_data:
        # Create new draft version instead of mutating published metric
        latest_version = await db.scalar(
            select(func.max(MetricDefinition.version)).where(
                MetricDefinition.data_source_id == existing.data_source_id,
                MetricDefinition.name == update_data.get("name", existing.name),
            )
        )
        new_version = int(latest_version or existing.version or 0) + 1
        metric = MetricDefinition(
            data_source_id=existing.data_source_id,
            name=update_data.get("name", existing.name),
            aliases=update_data.get("aliases", existing.aliases),
            formula=update_data.get("formula", existing.formula),
            underlying_columns=update_data.get("underlying_columns", existing.underlying_columns),
            agg_function=update_data.get("agg_function", existing.agg_function),
            business_definition=update_data.get(
                "business_definition", existing.business_definition
            ),
            required_filters=update_data.get("required_filters", existing.required_filters),
            time_field=update_data.get("time_field", existing.time_field),
            grain=update_data.get("grain", existing.grain),
            owner=update_data.get("owner", existing.owner),
            business_domain=update_data.get("business_domain", existing.business_domain),
            unit=update_data.get("unit", existing.unit),
            category=update_data.get("category", existing.category),
            tags=update_data.get("tags", existing.tags),
            sensitivity=update_data.get("sensitivity", existing.sensitivity),
            evidence_refs=update_data.get("evidence_refs", existing.evidence_refs),
            quality_contract=update_data.get("quality_contract", existing.quality_contract),
            valid_from=update_data.get("valid_from", existing.valid_from),
            valid_to=update_data.get("valid_to", existing.valid_to),
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
    http_request: Request,
    metric_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a metric definition."""
    result = await db.execute(
        _scoped_metrics_statement(http_request, current_user).where(
            MetricDefinition.id == metric_id
        )
    )
    metric = result.scalar()
    if not metric:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="metric not found")
    await _require_owned_source(db, http_request, current_user, metric.data_source_id, "edit")
    await db.delete(metric)
    await db.commit()
    return {"deleted": True, "metric_id": metric_id}


@router.post("/metrics/{metric_id}/publish")
async def publish_metric(
    http_request: Request,
    metric_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Publish a draft metric definition."""
    result = await db.execute(
        _scoped_metrics_statement(http_request, current_user).where(
            MetricDefinition.id == metric_id
        )
    )
    metric = result.scalar()
    if not metric:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="metric not found")
    await _require_owned_source(db, http_request, current_user, metric.data_source_id, "edit")
    if metric.status != "draft":
        raise AppException(
            ErrorCodes.PARAM_INVALID.code, message="only draft metrics can be published"
        )
    if not (current_user.is_superuser or current_user.role == "admin"):
        raise AppException(
            ErrorCodes.PERMISSION_DENIED.code,
            message="only an administrator can certify metric definitions",
        )

    missing_contract = _metric_certification_missing_fields(metric)
    if missing_contract:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message="metric certification contract is incomplete",
            details={"missing_fields": missing_contract},
        )

    _validate_effective_interval(metric.valid_from, metric.valid_to)
    published = list(
        (
            await db.execute(
                select(MetricDefinition).where(
                    MetricDefinition.data_source_id == metric.data_source_id,
                    MetricDefinition.name == metric.name,
                    MetricDefinition.status == "published",
                    MetricDefinition.id != metric.id,
                )
            )
        )
        .scalars()
        .all()
    )
    if metric.valid_from is None:
        metric.valid_from = datetime.now(UTC)
    for previous in published:
        metric_valid_from = _as_utc(metric.valid_from)
        if (
            metric_valid_from is not None
            and previous.valid_to is None
            and (_as_utc(previous.valid_from) or datetime.min.replace(tzinfo=UTC))
            < metric_valid_from
        ):
            previous.valid_to = metric.valid_from
        if _intervals_overlap(
            previous.valid_from,
            previous.valid_to,
            metric.valid_from,
            metric.valid_to,
        ):
            raise AppException(
                ErrorCodes.PARAM_INVALID.code,
                message="published metric versions must not have overlapping effective intervals",
            )

    metric.status = "published"
    metric.certification_level = "certified"
    metric.approved_by = current_user.id
    metric.approved_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(metric)
    return {"metric": _metric_to_dict(metric)}


@router.post("/metrics/{metric_id}/deprecate")
async def deprecate_metric(
    http_request: Request,
    metric_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deprecate a metric definition."""
    result = await db.execute(
        _scoped_metrics_statement(http_request, current_user).where(
            MetricDefinition.id == metric_id
        )
    )
    metric = result.scalar()
    if not metric:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="metric not found")
    await _require_owned_source(db, http_request, current_user, metric.data_source_id, "edit")

    metric.status = "deprecated"
    metric.certification_level = "deprecated"
    if metric.valid_to is None:
        metric.valid_to = datetime.now(UTC)
    await db.commit()
    await db.refresh(metric)
    return {"metric": _metric_to_dict(metric)}


@router.get("/metrics/{metric_id}/lineage")
async def get_metric_lineage(
    http_request: Request,
    metric_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get the lineage graph for a metric."""
    metric_result = await db.execute(
        _scoped_metrics_statement(http_request, current_user).where(
            MetricDefinition.id == metric_id
        )
    )
    if metric_result.scalar() is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="metric not found")
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
        "required_filters": m.required_filters,
        "time_field": m.time_field,
        "grain": m.grain,
        "owner": m.owner,
        "business_domain": m.business_domain,
        "unit": m.unit,
        "category": m.category,
        "tags": m.tags,
        "sensitivity": m.sensitivity,
        "certification_level": m.certification_level,
        "evidence_refs": m.evidence_refs,
        "quality_contract": m.quality_contract,
        "version": m.version,
        "status": m.status,
        "approved_by": m.approved_by,
        "approved_at": str(m.approved_at) if m.approved_at else None,
        "valid_from": str(m.valid_from) if m.valid_from else None,
        "valid_to": str(m.valid_to) if m.valid_to else None,
        "created_by": m.created_by,
        "created_at": str(m.created_at) if m.created_at else None,
        "updated_at": str(m.updated_at) if m.updated_at else None,
    }
