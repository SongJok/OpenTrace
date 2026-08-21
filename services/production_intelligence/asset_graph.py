"""PostgreSQL Production Asset Graph 服务。"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    EnterpriseConnector,
    ProductionAsset,
    ProductionAssetRelation,
)
from services.production_intelligence.audit import append_audit
from services.production_intelligence.domain import ASSET_TYPES, RELATION_TYPES


class AssetGraphError(ValueError):
    """资产图输入、范围或关系不合法。"""


@dataclass(frozen=True, slots=True)
class ProductionScope:
    tenant_id: str
    workspace_id: str
    user_id: str


def asset_to_dict(row: ProductionAsset) -> dict[str, Any]:
    return {
        "id": row.id,
        "asset_type": row.asset_type,
        "external_key": row.external_key,
        "name": row.name,
        "description": row.description,
        "environment": row.environment,
        "status": row.status,
        "criticality": row.criticality,
        "classification": row.classification,
        "connector_id": row.connector_id,
        "source_kind": row.source_kind,
        "source_key": row.source_key,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "last_sync_run_id": row.last_sync_run_id,
        "attributes": dict(row.attributes or {}),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def relation_to_dict(row: ProductionAssetRelation) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_asset_id": row.source_asset_id,
        "target_asset_id": row.target_asset_id,
        "relation_type": row.relation_type,
        "confidence": float(row.confidence),
        "source_kind": row.source_kind,
        "source_key": row.source_key,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "last_sync_run_id": row.last_sync_run_id,
        "attributes": dict(row.attributes or {}),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class AssetGraphService:
    """所有查询都显式绑定 tenant/workspace，禁止只凭资产 ID 返回。"""

    def __init__(self, db: AsyncSession, scope: ProductionScope) -> None:
        self.db = db
        self.scope = scope

    def _asset_scope(self):
        return (
            ProductionAsset.tenant_id == self.scope.tenant_id,
            ProductionAsset.workspace_id == self.scope.workspace_id,
        )

    def _relation_scope(self):
        return (
            ProductionAssetRelation.tenant_id == self.scope.tenant_id,
            ProductionAssetRelation.workspace_id == self.scope.workspace_id,
        )

    async def get_asset(self, asset_id: str) -> ProductionAsset | None:
        return await self.db.scalar(
            select(ProductionAsset).where(ProductionAsset.id == asset_id, *self._asset_scope())
        )

    async def require_asset(self, asset_id: str) -> ProductionAsset:
        row = await self.get_asset(asset_id)
        if row is None:
            raise AssetGraphError("asset_not_found")
        return row

    async def list_assets(
        self,
        *,
        asset_type: str | None = None,
        environment: str | None = None,
        status: str | None = "active",
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[ProductionAsset]:
        stmt = select(ProductionAsset).where(*self._asset_scope())
        if asset_type:
            if asset_type not in ASSET_TYPES:
                raise AssetGraphError("unsupported_asset_type")
            stmt = stmt.where(ProductionAsset.asset_type == asset_type)
        if environment:
            stmt = stmt.where(ProductionAsset.environment == environment)
        if status:
            stmt = stmt.where(ProductionAsset.status == status)
        if query.strip():
            term = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    ProductionAsset.name.ilike(term),
                    ProductionAsset.external_key.ilike(term),
                    ProductionAsset.description.ilike(term),
                )
            )
        result = await self.db.execute(
            stmt.order_by(ProductionAsset.asset_type, ProductionAsset.name)
            .offset(max(0, offset))
            .limit(max(1, min(limit, 500)))
        )
        return list(result.scalars().all())

    async def _validate_connector(self, connector_id: str | None) -> None:
        if not connector_id:
            return
        connector = await self.db.scalar(
            select(EnterpriseConnector).where(
                EnterpriseConnector.id == connector_id,
                EnterpriseConnector.tenant_id == self.scope.tenant_id,
                EnterpriseConnector.workspace_id == self.scope.workspace_id,
            )
        )
        if connector is None:
            raise AssetGraphError("connector_not_found")

    async def create_asset(
        self,
        *,
        asset_type: str,
        external_key: str,
        name: str,
        description: str = "",
        environment: str = "shared",
        status: str = "active",
        criticality: str = "medium",
        classification: str = "internal",
        connector_id: str | None = None,
        source_kind: str = "manual",
        attributes: dict[str, Any] | None = None,
    ) -> ProductionAsset:
        if asset_type not in ASSET_TYPES:
            raise AssetGraphError("unsupported_asset_type")
        if not external_key.strip() or not name.strip():
            raise AssetGraphError("asset_key_and_name_required")
        await self._validate_connector(connector_id)
        existing = await self.db.scalar(
            select(ProductionAsset).where(
                *self._asset_scope(),
                ProductionAsset.asset_type == asset_type,
                ProductionAsset.external_key == external_key.strip(),
            )
        )
        if existing is not None:
            raise AssetGraphError("asset_already_exists")
        row = ProductionAsset(
            id=str(uuid.uuid4()),
            tenant_id=self.scope.tenant_id,
            workspace_id=self.scope.workspace_id,
            asset_type=asset_type,
            external_key=external_key.strip(),
            name=name.strip(),
            description=description.strip(),
            environment=environment.strip() or "shared",
            status=status,
            criticality=criticality,
            classification=classification,
            connector_id=connector_id,
            source_kind=source_kind,
            attributes=dict(attributes or {}),
            created_by=self.scope.user_id,
        )
        self.db.add(row)
        # 后续审计和关系仅有纯外键，必须显式 flush 确保父资产先落库。
        await self.db.flush()
        append_audit(
            self.db,
            user_id=self.scope.user_id,
            action="production_asset.created",
            resource_type="production_asset",
            resource_id=row.id,
            payload={
                "asset_type": row.asset_type,
                "external_key": row.external_key,
                "environment": row.environment,
            },
        )
        return row

    async def update_asset(self, asset_id: str, changes: dict[str, Any]) -> ProductionAsset:
        row = await self.require_asset(asset_id)
        allowed = {
            "name",
            "description",
            "environment",
            "status",
            "criticality",
            "classification",
            "connector_id",
            "source_kind",
            "attributes",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise AssetGraphError(f"unsupported_asset_fields:{','.join(sorted(unknown))}")
        if "connector_id" in changes:
            await self._validate_connector(changes.get("connector_id"))
        for key, value in changes.items():
            if key in {"name", "description", "environment"} and isinstance(value, str):
                value = value.strip()
            if key == "name" and not value:
                raise AssetGraphError("asset_name_required")
            if key == "attributes":
                value = dict(value or {})
            setattr(row, key, value)
        append_audit(
            self.db,
            user_id=self.scope.user_id,
            action="production_asset.updated",
            resource_type="production_asset",
            resource_id=row.id,
            payload={"fields": sorted(changes)},
        )
        await self.db.flush()
        return row

    async def retire_asset(self, asset_id: str) -> ProductionAsset:
        row = await self.require_asset(asset_id)
        row.status = "retired"
        append_audit(
            self.db,
            user_id=self.scope.user_id,
            action="production_asset.retired",
            resource_type="production_asset",
            resource_id=row.id,
        )
        await self.db.flush()
        return row

    async def create_relation(
        self,
        *,
        source_asset_id: str,
        target_asset_id: str,
        relation_type: str,
        confidence: float = 1.0,
        source_kind: str = "manual",
        attributes: dict[str, Any] | None = None,
    ) -> ProductionAssetRelation:
        if relation_type not in RELATION_TYPES:
            raise AssetGraphError("unsupported_relation_type")
        if source_asset_id == target_asset_id:
            raise AssetGraphError("self_relation_not_allowed")
        if not 0.0 <= confidence <= 1.0:
            raise AssetGraphError("relation_confidence_out_of_range")
        await self.require_asset(source_asset_id)
        await self.require_asset(target_asset_id)
        existing = await self.db.scalar(
            select(ProductionAssetRelation).where(
                *self._relation_scope(),
                ProductionAssetRelation.source_asset_id == source_asset_id,
                ProductionAssetRelation.target_asset_id == target_asset_id,
                ProductionAssetRelation.relation_type == relation_type,
            )
        )
        if existing is not None:
            raise AssetGraphError("relation_already_exists")
        row = ProductionAssetRelation(
            id=str(uuid.uuid4()),
            tenant_id=self.scope.tenant_id,
            workspace_id=self.scope.workspace_id,
            source_asset_id=source_asset_id,
            target_asset_id=target_asset_id,
            relation_type=relation_type,
            confidence=confidence,
            source_kind=source_kind,
            attributes=dict(attributes or {}),
            created_by=self.scope.user_id,
        )
        self.db.add(row)
        await self.db.flush()
        append_audit(
            self.db,
            user_id=self.scope.user_id,
            action="production_asset_relation.created",
            resource_type="production_asset_relation",
            resource_id=row.id,
            payload={
                "source_asset_id": source_asset_id,
                "target_asset_id": target_asset_id,
                "relation_type": relation_type,
                "confidence": confidence,
            },
        )
        return row

    async def delete_relation(self, relation_id: str) -> None:
        row = await self.db.scalar(
            select(ProductionAssetRelation).where(
                ProductionAssetRelation.id == relation_id, *self._relation_scope()
            )
        )
        if row is None:
            raise AssetGraphError("relation_not_found")
        append_audit(
            self.db,
            user_id=self.scope.user_id,
            action="production_asset_relation.deleted",
            resource_type="production_asset_relation",
            resource_id=row.id,
            payload={
                "source_asset_id": row.source_asset_id,
                "target_asset_id": row.target_asset_id,
                "relation_type": row.relation_type,
            },
        )
        await self.db.delete(row)
        await self.db.flush()

    async def import_graph(
        self,
        *,
        assets: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        upsert: bool = True,
        source: str = "api_import",
        source_key: str | None = None,
        sync_run_id: str | None = None,
        observed_at: datetime | None = None,
        adopt_existing: bool = False,
    ) -> dict[str, Any]:
        """在同一事务中批量写入节点和边；调用方负责最终 commit/rollback。"""

        if not assets or len(assets) > 500 or len(relations) > 1000:
            raise AssetGraphError("asset_graph_import_size_invalid")
        normalized_source_key = str(source_key or "").strip() or None
        if bool(normalized_source_key) != bool(sync_run_id):
            raise AssetGraphError("asset_graph_sync_identity_incomplete")
        if normalized_source_key and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", normalized_source_key
        ):
            raise AssetGraphError("asset_graph_sync_source_key_invalid")
        keys = [
            (str(item.get("asset_type") or ""), str(item.get("external_key") or "").strip())
            for item in assets
        ]
        if any(
            asset_type not in ASSET_TYPES or not external_key for asset_type, external_key in keys
        ):
            raise AssetGraphError("asset_graph_import_asset_invalid")
        if len(set(keys)) != len(keys):
            raise AssetGraphError("asset_graph_import_duplicate_asset")

        existing_rows = await self.db.execute(
            select(ProductionAsset).where(
                *self._asset_scope(),
                tuple_(ProductionAsset.asset_type, ProductionAsset.external_key).in_(keys),
            )
        )
        by_key = {(row.asset_type, row.external_key): row for row in existing_rows.scalars().all()}
        if not upsert and by_key:
            raise AssetGraphError("asset_already_exists")

        connector_ids = {
            str(item.get("connector_id")) for item in assets if item.get("connector_id")
        }
        if connector_ids:
            connector_rows = await self.db.execute(
                select(EnterpriseConnector.id).where(
                    EnterpriseConnector.id.in_(connector_ids),
                    EnterpriseConnector.tenant_id == self.scope.tenant_id,
                    EnterpriseConnector.workspace_id == self.scope.workspace_id,
                )
            )
            if set(connector_rows.scalars().all()) != connector_ids:
                raise AssetGraphError("connector_not_found")

        created_assets = 0
        updated_assets = 0
        for item, key in zip(assets, keys, strict=True):
            row = by_key.get(key)
            if (
                normalized_source_key
                and row is not None
                and row.source_key != normalized_source_key
                and not adopt_existing
            ):
                raise AssetGraphError("asset_graph_sync_asset_ownership_conflict")
            values = {
                "name": str(item.get("name") or "").strip(),
                "description": str(item.get("description") or "").strip(),
                "environment": str(item.get("environment") or "shared").strip() or "shared",
                "status": str(item.get("status") or "active"),
                "criticality": str(item.get("criticality") or "medium"),
                "classification": str(item.get("classification") or "internal"),
                "connector_id": item.get("connector_id"),
                "source_kind": (
                    "sync" if normalized_source_key else str(item.get("source_kind") or "import")
                ),
                "attributes": dict(item.get("attributes") or {}),
            }
            if normalized_source_key:
                values.update(
                    source_key=normalized_source_key,
                    last_seen_at=observed_at,
                    last_sync_run_id=sync_run_id,
                )
            if not values["name"]:
                raise AssetGraphError("asset_key_and_name_required")
            if row is None:
                row = ProductionAsset(
                    id=str(uuid.uuid4()),
                    tenant_id=self.scope.tenant_id,
                    workspace_id=self.scope.workspace_id,
                    asset_type=key[0],
                    external_key=key[1],
                    created_by=self.scope.user_id,
                    **values,
                )
                self.db.add(row)
                by_key[key] = row
                created_assets += 1
            else:
                for field_name, value in values.items():
                    setattr(row, field_name, value)
                updated_assets += 1
        # 关系只有纯外键，必须在构造边之前确保所有父节点已有主键。
        await self.db.flush()

        relation_keys: list[tuple[str, str, str]] = []
        normalized_relations: list[tuple[ProductionAsset, ProductionAsset, dict[str, Any]]] = []
        for item in relations:
            source_asset_key = (
                str(item.get("source_asset_type") or ""),
                str(item.get("source_external_key") or "").strip(),
            )
            target_asset_key = (
                str(item.get("target_asset_type") or ""),
                str(item.get("target_external_key") or "").strip(),
            )
            relation_type = str(item.get("relation_type") or "")
            source_asset = by_key.get(source_asset_key)
            target_asset = by_key.get(target_asset_key)
            confidence = float(item.get("confidence", 1.0))
            if source_asset is None or target_asset is None:
                raise AssetGraphError("asset_graph_import_relation_asset_missing")
            if source_asset.id == target_asset.id:
                raise AssetGraphError("self_relation_not_allowed")
            if relation_type not in RELATION_TYPES or not 0.0 <= confidence <= 1.0:
                raise AssetGraphError("asset_graph_import_relation_invalid")
            edge_key = (source_asset.id, target_asset.id, relation_type)
            relation_keys.append(edge_key)
            normalized_relations.append((source_asset, target_asset, item))
        if len(set(relation_keys)) != len(relation_keys):
            raise AssetGraphError("asset_graph_import_duplicate_relation")

        existing_relations: dict[tuple[str, str, str], ProductionAssetRelation] = {}
        if relation_keys:
            relation_rows = await self.db.execute(
                select(ProductionAssetRelation).where(
                    *self._relation_scope(),
                    tuple_(
                        ProductionAssetRelation.source_asset_id,
                        ProductionAssetRelation.target_asset_id,
                        ProductionAssetRelation.relation_type,
                    ).in_(relation_keys),
                )
            )
            existing_relations = {
                (row.source_asset_id, row.target_asset_id, row.relation_type): row
                for row in relation_rows.scalars().all()
            }
        if not upsert and existing_relations:
            raise AssetGraphError("relation_already_exists")

        created_relations = 0
        updated_relations = 0
        for (source_asset, target_asset, item), edge_key in zip(
            normalized_relations, relation_keys, strict=True
        ):
            relation_row = existing_relations.get(edge_key)
            if (
                normalized_source_key
                and relation_row is not None
                and relation_row.source_key != normalized_source_key
                and not adopt_existing
            ):
                raise AssetGraphError("asset_graph_sync_relation_ownership_conflict")
            values = {
                "confidence": float(item.get("confidence", 1.0)),
                "source_kind": (
                    "sync" if normalized_source_key else str(item.get("source_kind") or "import")
                ),
                "attributes": dict(item.get("attributes") or {}),
            }
            if normalized_source_key:
                values.update(
                    source_key=normalized_source_key,
                    last_seen_at=observed_at,
                    last_sync_run_id=sync_run_id,
                )
            if relation_row is None:
                self.db.add(
                    ProductionAssetRelation(
                        id=str(uuid.uuid4()),
                        tenant_id=self.scope.tenant_id,
                        workspace_id=self.scope.workspace_id,
                        source_asset_id=source_asset.id,
                        target_asset_id=target_asset.id,
                        relation_type=edge_key[2],
                        created_by=self.scope.user_id,
                        **values,
                    )
                )
                created_relations += 1
            else:
                for field_name, value in values.items():
                    setattr(relation_row, field_name, value)
                updated_relations += 1
        await self.db.flush()
        append_audit(
            self.db,
            user_id=self.scope.user_id,
            action="production_asset_graph.imported",
            resource_type="production_asset_graph",
            resource_id=self.scope.workspace_id,
            payload={
                "source": source[:128],
                "upsert": upsert,
                "created_assets": created_assets,
                "updated_assets": updated_assets,
                "created_relations": created_relations,
                "updated_relations": updated_relations,
            },
        )
        return {
            "created_assets": created_assets,
            "updated_assets": updated_assets,
            "created_relations": created_relations,
            "updated_relations": updated_relations,
            "asset_ids": {
                f"{asset_type}:{external_key}": row.id
                for (asset_type, external_key), row in by_key.items()
                if (asset_type, external_key) in set(keys)
            },
        }

    async def neighborhood(
        self,
        asset_id: str,
        *,
        depth: int = 2,
        max_nodes: int = 200,
        max_edges: int = 500,
    ) -> dict[str, Any]:
        root = await self.require_asset(asset_id)
        nodes: dict[str, ProductionAsset] = {root.id: root}
        edges: dict[str, ProductionAssetRelation] = {}
        frontier = {root.id}
        truncated = False

        for _level in range(max(0, min(depth, 4))):
            if not frontier or len(nodes) >= max_nodes or len(edges) >= max_edges:
                truncated = bool(frontier)
                break
            relation_result = await self.db.execute(
                select(ProductionAssetRelation)
                .where(
                    *self._relation_scope(),
                    or_(
                        ProductionAssetRelation.source_asset_id.in_(frontier),
                        ProductionAssetRelation.target_asset_id.in_(frontier),
                    ),
                )
                .limit(max_edges - len(edges) + 1)
            )
            level_edges = list(relation_result.scalars().all())
            if len(level_edges) > max_edges - len(edges):
                level_edges = level_edges[: max_edges - len(edges)]
                truncated = True
            candidate_ids: set[str] = set()
            for edge in level_edges:
                edges[edge.id] = edge
                candidate_ids.add(edge.source_asset_id)
                candidate_ids.add(edge.target_asset_id)
            candidate_ids.difference_update(nodes)
            if len(candidate_ids) > max_nodes - len(nodes):
                candidate_ids = set(sorted(candidate_ids)[: max_nodes - len(nodes)])
                truncated = True
            if candidate_ids:
                asset_result = await self.db.execute(
                    select(ProductionAsset).where(
                        *self._asset_scope(), ProductionAsset.id.in_(candidate_ids)
                    )
                )
                for node in asset_result.scalars().all():
                    nodes[node.id] = node
            frontier = candidate_ids & set(nodes)

        visible_edges = [
            edge
            for edge in edges.values()
            if edge.source_asset_id in nodes and edge.target_asset_id in nodes
        ]
        return {
            "root_asset_id": root.id,
            "nodes": [asset_to_dict(node) for node in nodes.values()],
            "edges": [relation_to_dict(edge) for edge in visible_edges],
            "depth": max(0, min(depth, 4)),
            "truncated": truncated,
        }
