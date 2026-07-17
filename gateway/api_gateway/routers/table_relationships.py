"""
Table Relationships CRUD API — manage table_relationships knowledge assets.

Endpoints:
  GET  /api/v1/table-relationships — list relationships (by data_source_id, tables)
  POST /api/v1/table-relationships — create relationship
  GET  /api/v1/table-relationships/{rel_id} — get single relationship
  PUT  /api/v1/table-relationships/{rel_id} — update relationship
  DELETE /api/v1/table-relationships/{rel_id} — delete relationship
  POST /api/v1/table-relationships/{rel_id}/verify — mark as verified
  GET  /api/v1/table-relationships/graph?data_source_id= — get join graph for DAG view
  POST /api/v1/table-relationships/import-fk — import FK from information_schema
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.resource_scope import accessible_data_sources_statement, get_accessible_data_source
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import DataSource, TableRelationship, User

router = APIRouter()


def _scoped_relationships_statement(request: Request, current_user: User):
    tenant_md = build_tenant_metadata(request, user_id=current_user.id)
    accessible_ids = accessible_data_sources_statement(
        user_id=current_user.id, tenant_metadata=tenant_md, required_permission="view",
    ).with_only_columns(DataSource.id)
    return (
        select(TableRelationship)
        .where(TableRelationship.data_source_id.in_(accessible_ids))
    )


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

class RelationshipCreateRequest(BaseModel):
    data_source_id: str = Field(..., min_length=1, max_length=36)
    left_table: str = Field(..., min_length=1, max_length=255)
    left_column: str = Field(..., min_length=1, max_length=255)
    right_table: str = Field(..., min_length=1, max_length=255)
    right_column: str = Field(..., min_length=1, max_length=255)
    join_type: str = Field(default="LEFT")
    cardinality: str | None = None
    amplification_risk: str | None = None


class RelationshipUpdateRequest(BaseModel):
    left_table: str | None = None
    left_column: str | None = None
    right_table: str | None = None
    right_column: str | None = None
    join_type: str | None = None
    cardinality: str | None = None
    amplification_risk: str | None = None


# ── Routes ──────────────────────────────────────────────────────────

@router.get("/table-relationships")
async def list_relationships(
    http_request: Request,
    data_source_id: str = Query(default=""),
    table_name: str = Query(default=""),
    is_verified: bool | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List table relationships with optional filtering."""
    conditions = []
    if data_source_id:
        conditions.append(TableRelationship.data_source_id == data_source_id)
    if table_name:
        conditions.append(
            (TableRelationship.left_table == table_name)
            | (TableRelationship.right_table == table_name)
        )
    if is_verified is not None:
        conditions.append(TableRelationship.is_verified == is_verified)

    query = _scoped_relationships_statement(http_request, current_user)
    if conditions:
        query = query.where(and_(*conditions))
    query = query.order_by(
        TableRelationship.is_verified.desc(),
        TableRelationship.success_rate.desc(),
        TableRelationship.usage_count.desc(),
    ).offset(offset).limit(limit)

    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "items": [_rel_to_dict(r) for r in items],
        "total": len(items),
    }


@router.get("/table-relationships/graph")
async def get_relationship_graph(
    http_request: Request,
    data_source_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _build_relationship_graph(
        http_request=http_request,
        data_source_id=data_source_id,
        current_user=current_user,
        db=db,
    )


@router.get("/table-relationships/{rel_id}")
async def get_relationship(
    http_request: Request,
    rel_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single table relationship."""
    result = await db.execute(
        _scoped_relationships_statement(http_request, current_user).where(
            TableRelationship.id == rel_id
        )
    )
    rel = result.scalar()
    if not rel:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="relationship not found")
    return {"relationship": _rel_to_dict(rel)}


@router.post("/table-relationships")
async def create_relationship(
    http_request: Request,
    req: RelationshipCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new table relationship."""
    await _require_owned_source(db, http_request, current_user, req.data_source_id, "edit")
    rel = TableRelationship(
        data_source_id=req.data_source_id,
        left_table=req.left_table,
        left_column=req.left_column,
        right_table=req.right_table,
        right_column=req.right_column,
        join_type=req.join_type,
        cardinality=req.cardinality,
        amplification_risk=req.amplification_risk,
    )
    db.add(rel)
    await db.commit()
    await db.refresh(rel)
    return {"relationship": _rel_to_dict(rel)}


@router.put("/table-relationships/{rel_id}")
async def update_relationship(
    http_request: Request,
    rel_id: str,
    req: RelationshipUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update a table relationship."""
    result = await db.execute(
        _scoped_relationships_statement(http_request, current_user).where(
            TableRelationship.id == rel_id
        )
    )
    rel = result.scalar()
    if not rel:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="relationship not found")
    await _require_owned_source(db, http_request, current_user, rel.data_source_id, "edit")

    for key, val in req.dict(exclude_unset=True, exclude_none=True).items():
        setattr(rel, key, val)
    await db.commit()
    await db.refresh(rel)
    return {"relationship": _rel_to_dict(rel)}


@router.delete("/table-relationships/{rel_id}")
async def delete_relationship(
    http_request: Request,
    rel_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a table relationship."""
    result = await db.execute(
        _scoped_relationships_statement(http_request, current_user).where(
            TableRelationship.id == rel_id
        )
    )
    rel = result.scalar()
    if not rel:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="relationship not found")
    await _require_owned_source(db, http_request, current_user, rel.data_source_id, "edit")
    await db.delete(rel)
    await db.commit()
    return {"deleted": True, "relationship_id": rel_id}


@router.post("/table-relationships/{rel_id}/verify")
async def verify_relationship(
    http_request: Request,
    rel_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mark a table relationship as verified."""
    from datetime import datetime, timezone

    result = await db.execute(
        _scoped_relationships_statement(http_request, current_user).where(
            TableRelationship.id == rel_id
        )
    )
    rel = result.scalar()
    if not rel:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="relationship not found")
    await _require_owned_source(db, http_request, current_user, rel.data_source_id, "edit")

    rel.is_verified = True
    rel.verified_by = current_user.id
    rel.verified_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(rel)
    return {"relationship": _rel_to_dict(rel)}


async def _build_relationship_graph(
    http_request: Request,
    data_source_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get the full join graph for a data source (nodes + edges for DAG visualization)."""
    await _require_owned_source(db, http_request, current_user, data_source_id)
    result = await db.execute(
        _scoped_relationships_statement(http_request, current_user).where(
            TableRelationship.data_source_id == data_source_id
        ).order_by(
            TableRelationship.is_verified.desc(),
            TableRelationship.usage_count.desc(),
        )
    )
    relationships = result.scalars().all()

    # Build graph: nodes = tables, edges = relationships
    tables: dict[str, dict] = {}
    edges: list[dict] = []

    for rel in relationships:
        for t in (rel.left_table, rel.right_table):
            if t not in tables:
                tables[t] = {"name": t, "edge_count": 0}

        tables[rel.left_table]["edge_count"] += 1
        tables[rel.right_table]["edge_count"] += 1

        edges.append({
            "id": rel.id,
            "source": rel.left_table,
            "target": rel.right_table,
            "source_column": rel.left_column,
            "target_column": rel.right_column,
            "join_type": rel.join_type,
            "cardinality": rel.cardinality,
            "is_verified": rel.is_verified,
            "amplification_risk": rel.amplification_risk,
            "success_rate": rel.success_rate,
            "usage_count": rel.usage_count,
        })

    return {
        "data_source_id": data_source_id,
        "nodes": list(tables.values()),
        "edges": edges,
        "total_relationships": len(relationships),
        "verified_count": sum(1 for r in relationships if r.is_verified),
    }


def _rel_to_dict(r: TableRelationship) -> dict:
    return {
        "id": r.id,
        "data_source_id": r.data_source_id,
        "left_table": r.left_table,
        "left_column": r.left_column,
        "right_table": r.right_table,
        "right_column": r.right_column,
        "join_type": r.join_type,
        "cardinality": r.cardinality,
        "amplification_risk": r.amplification_risk,
        "is_verified": r.is_verified,
        "verified_by": r.verified_by,
        "verified_at": str(r.verified_at) if r.verified_at else None,
        "usage_count": r.usage_count,
        "success_rate": r.success_rate,
        "created_at": str(r.created_at) if r.created_at else None,
    }
