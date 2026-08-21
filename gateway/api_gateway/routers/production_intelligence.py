"""Production Asset Graph 与 Connector Catalog 管理 API。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal, NoReturn

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.security.identity import is_enterprise_admin
from infra.security.resource_scope import normalized_tenant_scope
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import User
from services.production_intelligence.asset_graph import (
    AssetGraphError,
    AssetGraphService,
    ProductionScope,
    asset_to_dict,
    relation_to_dict,
)
from services.production_intelligence.asset_sync import (
    AssetSyncError,
    ProductionAssetSyncService,
    asset_sync_run_to_dict,
)
from services.production_intelligence.config_intelligence import (
    ConfigIntelligenceError,
    ConfigIntelligenceService,
    policy_to_dict,
    snapshot_to_dict,
    validation_run_to_dict,
)
from services.production_intelligence.connectors import (
    ConnectorCatalogError,
    ConnectorCatalogService,
    connector_to_dict,
)
from services.production_intelligence.policy import CapabilityPolicy
from tenant.tenant_rls import set_session_scope

router = APIRouter()

AssetTypeValue = Literal[
    "business_domain",
    "service",
    "repository",
    "deployment",
    "config",
    "database",
    "table",
    "dashboard",
    "alert",
    "owner",
    "runbook",
    "business_api",
]
RelationTypeValue = Literal[
    "contains",
    "owned_by",
    "depends_on",
    "repository_for",
    "deployed_as",
    "configured_by",
    "reads_from",
    "writes_to",
    "monitored_by",
    "documented_by",
    "exposes",
]
ConnectorKindValue = Literal[
    "data",
    "observability",
    "knowledge",
    "code",
    "business",
    "config",
    "cicd",
    "cmdb",
    "kubernetes",
]


def _bounded_json(value: dict[str, Any], *, field_name: str) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) > 65_536:
        raise ValueError(f"{field_name} 不能超过 64 KiB")
    return value


class AssetCreateRequest(BaseModel):
    asset_type: AssetTypeValue
    external_key: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=10_000)
    environment: str = Field(default="shared", pattern="^[a-zA-Z0-9_.-]{1,32}$")
    status: str = Field(default="active", pattern="^(active|degraded|retired)$")
    criticality: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    classification: str = Field(
        default="internal", pattern="^(public|internal|confidential|restricted)$"
    )
    connector_id: str | None = Field(default=None, max_length=36)
    source_kind: str = Field(default="manual", pattern="^(manual|sync|import|inferred)$")
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(value, field_name="attributes")


class AssetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    environment: str | None = Field(default=None, pattern="^[a-zA-Z0-9_.-]{1,32}$")
    status: str | None = Field(default=None, pattern="^(active|degraded|retired)$")
    criticality: str | None = Field(default=None, pattern="^(low|medium|high|critical)$")
    classification: str | None = Field(
        default=None, pattern="^(public|internal|confidential|restricted)$"
    )
    connector_id: str | None = Field(default=None, max_length=36)
    source_kind: str | None = Field(default=None, pattern="^(manual|sync|import|inferred)$")
    attributes: dict[str, Any] | None = None

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return _bounded_json(value, field_name="attributes") if value is not None else None


class RelationCreateRequest(BaseModel):
    source_asset_id: str = Field(min_length=1, max_length=36)
    target_asset_id: str = Field(min_length=1, max_length=36)
    relation_type: RelationTypeValue
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_kind: str = Field(default="manual", pattern="^(manual|sync|import|inferred)$")
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(value, field_name="attributes")


class GraphImportAssetRequest(AssetCreateRequest):
    source_kind: Literal["import", "sync"] = "import"


class GraphImportRelationRequest(BaseModel):
    source_asset_type: AssetTypeValue
    source_external_key: str = Field(min_length=1, max_length=255)
    target_asset_type: AssetTypeValue
    target_external_key: str = Field(min_length=1, max_length=255)
    relation_type: RelationTypeValue
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_kind: Literal["import", "sync"] = "import"
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(value, field_name="attributes")


class GraphImportRequest(BaseModel):
    assets: list[GraphImportAssetRequest] = Field(min_length=1, max_length=500)
    relations: list[GraphImportRelationRequest] = Field(default_factory=list, max_length=1000)
    upsert: bool = True
    source: str = Field(default="api_import", min_length=1, max_length=128)


class GraphSyncRequest(BaseModel):
    source_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
    connector_id: str | None = Field(default=None, max_length=36)
    cursor_before: str | None = Field(default=None, max_length=512)
    cursor_after: str | None = Field(default=None, max_length=512)
    authoritative: bool = False
    adopt_existing: bool = False
    assets: list[GraphImportAssetRequest] = Field(default_factory=list, max_length=500)
    relations: list[GraphImportRelationRequest] = Field(default_factory=list, max_length=1000)


class ConnectorCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    connector_kind: ConnectorKindValue
    transport: Literal["mcp", "native", "rest", "rpc"] = "native"
    endpoint: str | None = Field(default=None, max_length=1024)
    secret_ref: str | None = Field(default=None, max_length=512, repr=False)
    status: Literal["disabled", "enabled", "degraded"] = "disabled"
    allowed_operations: list[str] = Field(default_factory=list, max_length=64)
    allowed_environments: list[str] = Field(default_factory=list, max_length=16)
    data_classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("allowed_operations")
    @classmethod
    def validate_operations(cls, value: list[str]) -> list[str]:
        for item in value:
            if (
                not item
                or len(item) > 128
                or not all(char.isalnum() or char in "_.-" for char in item)
            ):
                raise ValueError("连接器操作名不合法")
        return value

    @field_validator("allowed_environments")
    @classmethod
    def validate_environments(cls, value: list[str]) -> list[str]:
        for item in value:
            if (
                not item
                or len(item) > 32
                or not all(char.isalnum() or char in "_.-" for char in item)
            ):
                raise ValueError("连接器环境名不合法")
        return value

    @field_validator("config")
    @classmethod
    def validate_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(value, field_name="config")


class ConnectorUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    transport: Literal["mcp", "native", "rest", "rpc"] | None = None
    endpoint: str | None = Field(default=None, max_length=1024)
    secret_ref: str | None = Field(default=None, max_length=512, repr=False)
    status: Literal["disabled", "enabled", "degraded"] | None = None
    allowed_operations: list[str] | None = Field(default=None, max_length=64)
    allowed_environments: list[str] | None = Field(default=None, max_length=16)
    data_classification: Literal["public", "internal", "confidential", "restricted"] | None = None
    config: dict[str, Any] | None = None

    @field_validator("config")
    @classmethod
    def validate_config(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return _bounded_json(value, field_name="config") if value is not None else None


class ConfigPolicyCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    json_schema: dict[str, Any] = Field(alias="schema")
    reference_rules: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    business_rules: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    history_rules: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    capacity_rules: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    conflict_rules: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    dry_run_operation: str | None = Field(default=None, max_length=128)

    @field_validator(
        "json_schema",
        "reference_rules",
        "business_rules",
        "history_rules",
        "capacity_rules",
        "conflict_rules",
    )
    @classmethod
    def validate_policy_json(cls, value: Any) -> Any:
        encoded = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        if len(encoded) > 262_144:
            raise ValueError("配置策略字段不能超过 256 KiB")
        return value


class ConfigSnapshotCreateRequest(BaseModel):
    environment: str = Field(default="shared", pattern="^[a-zA-Z0-9_.-]{1,32}$")
    version_ref: str = Field(min_length=1, max_length=255)
    source_ref: str = Field(min_length=1, max_length=2048)
    status: Literal["current", "historical", "candidate", "applied", "rejected"] = "current"
    content: dict[str, Any]
    policy_id: str | None = Field(default=None, max_length=36)
    observed_at: datetime | None = None

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        if len(encoded) > 262_144:
            raise ValueError("配置快照不能超过 256 KiB")
        return value


class ConfigValidateRequest(BaseModel):
    environment: str = Field(default="shared", pattern="^[a-zA-Z0-9_.-]{1,32}$")
    candidate: dict[str, Any]

    @field_validator("candidate")
    @classmethod
    def validate_candidate(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        if len(encoded) > 262_144:
            raise ValueError("候选配置不能超过 256 KiB")
        return value


async def _scope(request: Request, user: User, db: AsyncSession) -> ProductionScope:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=user.id)
    )
    await set_session_scope(db, tenant_id=tenant_id, workspace_id=workspace_id)
    return ProductionScope(tenant_id, workspace_id, user.id)


def _require_admin(user: User) -> None:
    if not is_enterprise_admin(user):
        raise AppException(ErrorCodes.PERMISSION_DENIED.code, message="只有管理员可以修改生产资产")


def _require_config_read(user: User) -> None:
    decision = CapabilityPolicy().authorize(
        role=user.role,
        is_superuser=user.is_superuser,
        domain="config",
        risk="read",
    )
    if not decision.allowed:
        raise AppException(
            ErrorCodes.PERMISSION_DENIED.code, message="当前角色无权读取配置智能资产"
        )


def _raise_domain_error(exc: ValueError) -> NoReturn:
    message = str(exc)
    if message.endswith("_not_found"):
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message=message) from exc
    if message.endswith("_already_exists"):
        raise AppException(ErrorCodes.RESOURCE_EXISTS.code, message=message) from exc
    raise AppException(ErrorCodes.PARAM_INVALID.code, message=message) from exc


@router.get("/production/assets")
async def list_production_assets(
    request: Request,
    asset_type: AssetTypeValue | None = None,
    environment: str | None = Query(default=None, max_length=32),
    status: str | None = Query(default="active", pattern="^(active|degraded|retired)$"),
    q: str = Query(default="", max_length=255),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = AssetGraphService(db, await _scope(request, current_user, db))
    try:
        rows = await service.list_assets(
            asset_type=asset_type,
            environment=environment,
            status=status,
            query=q,
            limit=limit,
            offset=offset,
        )
    except AssetGraphError as exc:
        _raise_domain_error(exc)
    return {"items": [asset_to_dict(row) for row in rows], "limit": limit, "offset": offset}


@router.get("/production/asset-graph")
async def get_production_asset_graph(
    request: Request,
    asset_id: str = Query(min_length=1, max_length=36),
    depth: int = Query(default=2, ge=0, le=4),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = AssetGraphService(db, await _scope(request, current_user, db))
    try:
        return await service.neighborhood(asset_id, depth=depth)
    except AssetGraphError as exc:
        _raise_domain_error(exc)


@router.post("/production/asset-graph/import")
async def import_production_asset_graph(
    payload: GraphImportRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = AssetGraphService(db, await _scope(request, current_user, db))
    try:
        result = await service.import_graph(
            assets=[item.model_dump() for item in payload.assets],
            relations=[item.model_dump() for item in payload.relations],
            upsert=payload.upsert,
            source=payload.source,
        )
        await db.commit()
    except AssetGraphError as exc:
        await db.rollback()
        _raise_domain_error(exc)
    return result


@router.post("/production/asset-graph/sync")
async def sync_production_asset_graph(
    payload: GraphSyncRequest,
    request: Request,
    idempotency_key: str = Header(min_length=1, max_length=255, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = ProductionAssetSyncService(db, await _scope(request, current_user, db))
    try:
        run = await service.run_sync(
            source_key=payload.source_key,
            connector_id=payload.connector_id,
            idempotency_key=idempotency_key,
            cursor_before=payload.cursor_before,
            cursor_after=payload.cursor_after,
            authoritative=payload.authoritative,
            adopt_existing=payload.adopt_existing,
            assets=[item.model_dump() for item in payload.assets],
            relations=[item.model_dump() for item in payload.relations],
        )
    except (AssetGraphError, AssetSyncError) as exc:
        _raise_domain_error(exc)
    return asset_sync_run_to_dict(run)


@router.get("/production/asset-sync-runs")
async def list_production_asset_sync_runs(
    request: Request,
    source_key: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = ProductionAssetSyncService(db, await _scope(request, current_user, db))
    rows = await service.list_runs(source_key=source_key, limit=limit)
    return {"items": [asset_sync_run_to_dict(row) for row in rows]}


@router.get("/production/asset-sync-runs/{run_id}")
async def get_production_asset_sync_run(
    run_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = ProductionAssetSyncService(db, await _scope(request, current_user, db))
    row = await service.get(run_id)
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="asset_sync_run_not_found")
    return asset_sync_run_to_dict(row)


@router.get("/production/assets/{asset_id}")
async def get_production_asset(
    asset_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = AssetGraphService(db, await _scope(request, current_user, db))
    row = await service.get_asset(asset_id)
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="asset_not_found")
    return asset_to_dict(row)


@router.post("/production/assets", status_code=201)
async def create_production_asset(
    payload: AssetCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = AssetGraphService(db, await _scope(request, current_user, db))
    try:
        row = await service.create_asset(**payload.model_dump())
        await db.commit()
    except AssetGraphError as exc:
        _raise_domain_error(exc)
    return asset_to_dict(row)


@router.patch("/production/assets/{asset_id}")
async def update_production_asset(
    asset_id: str,
    payload: AssetUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = AssetGraphService(db, await _scope(request, current_user, db))
    try:
        row = await service.update_asset(asset_id, payload.model_dump(exclude_unset=True))
        await db.commit()
    except AssetGraphError as exc:
        _raise_domain_error(exc)
    return asset_to_dict(row)


@router.delete("/production/assets/{asset_id}")
async def retire_production_asset(
    asset_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = AssetGraphService(db, await _scope(request, current_user, db))
    try:
        row = await service.retire_asset(asset_id)
        await db.commit()
    except AssetGraphError as exc:
        _raise_domain_error(exc)
    return {"id": row.id, "status": row.status}


@router.post("/production/asset-relations", status_code=201)
async def create_production_asset_relation(
    payload: RelationCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = AssetGraphService(db, await _scope(request, current_user, db))
    try:
        row = await service.create_relation(**payload.model_dump())
        await db.commit()
    except AssetGraphError as exc:
        _raise_domain_error(exc)
    return relation_to_dict(row)


@router.delete("/production/asset-relations/{relation_id}")
async def delete_production_asset_relation(
    relation_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = AssetGraphService(db, await _scope(request, current_user, db))
    try:
        await service.delete_relation(relation_id)
        await db.commit()
    except AssetGraphError as exc:
        _raise_domain_error(exc)
    return {"id": relation_id, "deleted": True}


@router.get("/production/connectors")
async def list_enterprise_connectors(
    request: Request,
    connector_kind: ConnectorKindValue | None = None,
    status: str | None = Query(default=None, pattern="^(disabled|enabled|degraded)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = ConnectorCatalogService(db, await _scope(request, current_user, db))
    try:
        rows = await service.list(connector_kind=connector_kind, status=status)
    except ConnectorCatalogError as exc:
        _raise_domain_error(exc)
    return {"items": [connector_to_dict(row) for row in rows]}


@router.post("/production/connectors", status_code=201)
async def create_enterprise_connector(
    payload: ConnectorCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = ConnectorCatalogService(db, await _scope(request, current_user, db))
    try:
        row = await service.create(**payload.model_dump())
        await db.commit()
    except ConnectorCatalogError as exc:
        _raise_domain_error(exc)
    return connector_to_dict(row)


@router.patch("/production/connectors/{connector_id}")
async def update_enterprise_connector(
    connector_id: str,
    payload: ConnectorUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = ConnectorCatalogService(db, await _scope(request, current_user, db))
    try:
        row = await service.update(connector_id, payload.model_dump(exclude_unset=True))
        await db.commit()
    except ConnectorCatalogError as exc:
        _raise_domain_error(exc)
    return connector_to_dict(row)


@router.get("/production/capability-policy")
async def get_current_capability_policy(
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    return CapabilityPolicy().role_projection(
        current_user.role, is_superuser=current_user.is_superuser
    )


@router.get("/production/config-assets/{asset_id}/policies")
async def list_config_policies(
    asset_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_config_read(current_user)
    service = ConfigIntelligenceService(db, await _scope(request, current_user, db))
    try:
        rows = await service.policies(asset_id, limit=limit)
    except ConfigIntelligenceError as exc:
        _raise_domain_error(exc)
    return {"items": [policy_to_dict(row) for row in rows]}


@router.post("/production/config-assets/{asset_id}/policies", status_code=201)
async def create_config_policy(
    asset_id: str,
    payload: ConfigPolicyCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = ConfigIntelligenceService(db, await _scope(request, current_user, db))
    values = payload.model_dump(by_alias=True)
    try:
        row = await service.create_policy(asset_id=asset_id, **values)
        await db.commit()
    except ConfigIntelligenceError as exc:
        _raise_domain_error(exc)
    return policy_to_dict(row)


@router.post("/production/config-policies/{policy_id}/publish")
async def publish_config_policy(
    policy_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = ConfigIntelligenceService(db, await _scope(request, current_user, db))
    try:
        row = await service.publish_policy(policy_id)
        await db.commit()
    except ConfigIntelligenceError as exc:
        _raise_domain_error(exc)
    return policy_to_dict(row)


@router.get("/production/config-assets/{asset_id}/snapshots")
async def list_config_snapshots(
    asset_id: str,
    request: Request,
    environment: str = Query(default="shared", max_length=32),
    limit: int = Query(default=20, ge=1, le=100),
    include_content: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_config_read(current_user)
    if include_content:
        _require_admin(current_user)
    service = ConfigIntelligenceService(db, await _scope(request, current_user, db))
    try:
        await service.require_config_asset(asset_id)
        rows = await service.snapshots(asset_id, environment=environment, limit=limit)
    except ConfigIntelligenceError as exc:
        _raise_domain_error(exc)
    return {"items": [snapshot_to_dict(row, include_content=include_content) for row in rows]}


@router.post("/production/config-assets/{asset_id}/snapshots", status_code=201)
async def create_config_snapshot(
    asset_id: str,
    payload: ConfigSnapshotCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    service = ConfigIntelligenceService(db, await _scope(request, current_user, db))
    try:
        row = await service.record_snapshot(asset_id=asset_id, **payload.model_dump())
        await db.commit()
    except ConfigIntelligenceError as exc:
        _raise_domain_error(exc)
    return snapshot_to_dict(row, include_content=True)


@router.post("/production/config-assets/{asset_id}/validate", status_code=201)
async def validate_config_candidate(
    asset_id: str,
    payload: ConfigValidateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_config_read(current_user)
    service = ConfigIntelligenceService(db, await _scope(request, current_user, db))
    try:
        run, report = await service.validate_and_record(
            asset_id=asset_id,
            candidate=payload.candidate,
            response_id=None,
            environment=payload.environment,
            dry_run={},
        )
        await db.commit()
    except ConfigIntelligenceError as exc:
        _raise_domain_error(exc)
    return {"run": validation_run_to_dict(run), "report": report.to_dict()}


@router.get("/production/config-assets/{asset_id}/validation-runs")
async def list_config_validation_runs(
    asset_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_config_read(current_user)
    service = ConfigIntelligenceService(db, await _scope(request, current_user, db))
    try:
        rows = await service.validation_runs(asset_id, limit=limit)
    except ConfigIntelligenceError as exc:
        _raise_domain_error(exc)
    return {"items": [validation_run_to_dict(row) for row in rows]}
