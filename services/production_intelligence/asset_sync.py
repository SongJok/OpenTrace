"""Production Asset Graph 的持久化增量/权威同步运行时。"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from infra.observability.metrics import (
    PRODUCTION_ASSET_SYNC_DURATION,
    PRODUCTION_ASSET_SYNC_TOTAL,
)
from infra.storage.models import (
    EnterpriseConnector,
    ProductionAsset,
    ProductionAssetRelation,
    ProductionAssetSyncRun,
)
from services.production_intelligence.asset_graph import (
    AssetGraphError,
    AssetGraphService,
    ProductionScope,
)
from services.production_intelligence.audit import append_audit


class AssetSyncError(ValueError):
    """资产同步租约、游标、幂等或来源所有权不合法。"""


def asset_sync_run_to_dict(row: ProductionAssetSyncRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_key": row.source_key,
        "connector_id": row.connector_id,
        "status": row.status,
        "idempotency_key": row.idempotency_key,
        "input_hash": row.input_hash,
        "cursor_before": row.cursor_before,
        "cursor_after": row.cursor_after,
        "authoritative": row.authoritative,
        "attempt_count": row.attempt_count,
        "lease_expires_at": row.lease_expires_at.isoformat() if row.lease_expires_at else None,
        "heartbeat_at": row.heartbeat_at.isoformat() if row.heartbeat_at else None,
        "stats": dict(row.stats or {}),
        "requested_by": row.requested_by,
        "error": row.error,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _input_hash(
    *,
    source_key: str,
    connector_id: str | None,
    cursor_before: str | None,
    cursor_after: str | None,
    authoritative: bool,
    adopt_existing: bool,
    assets: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> str:
    encoded = json.dumps(
        {
            "source_key": source_key,
            "connector_id": connector_id,
            "cursor_before": cursor_before,
            "cursor_after": cursor_after,
            "authoritative": authoritative,
            "adopt_existing": adopt_existing,
            "assets": assets,
            "relations": relations,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


class ProductionAssetSyncService:
    """同步运行先持久化租约，再原子更新资产图，失败状态独立提交。"""

    def __init__(
        self,
        db: AsyncSession,
        scope: ProductionScope,
        *,
        lease_seconds: int = 300,
        lease_owner: str | None = None,
    ) -> None:
        self.db = db
        self.scope = scope
        self.lease_seconds = max(30, min(int(lease_seconds), 900))
        self.lease_owner = (lease_owner or f"asset-sync-{uuid.uuid4()}")[:128]

    def _scope_filter(self) -> tuple[Any, Any]:
        return (
            ProductionAssetSyncRun.tenant_id == self.scope.tenant_id,
            ProductionAssetSyncRun.workspace_id == self.scope.workspace_id,
        )

    async def _advisory_lock(self, source_key: str) -> None:
        try:
            dialect = self.db.get_bind().dialect.name
        except (AttributeError, RuntimeError):
            dialect = ""
        if dialect == "postgresql":
            await self.db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:scope_key))"),
                {
                    "scope_key": (
                        f"production_asset_sync:{self.scope.tenant_id}:"
                        f"{self.scope.workspace_id}:{source_key}"
                    )
                },
            )

    async def _validate_connector(self, connector_id: str | None) -> None:
        if not connector_id:
            return
        connector = await self.db.scalar(
            select(EnterpriseConnector.id).where(
                EnterpriseConnector.id == connector_id,
                EnterpriseConnector.tenant_id == self.scope.tenant_id,
                EnterpriseConnector.workspace_id == self.scope.workspace_id,
                EnterpriseConnector.status.in_(("enabled", "degraded")),
            )
        )
        if connector is None:
            raise AssetSyncError("asset_sync_connector_not_found")

    async def get(self, run_id: str) -> ProductionAssetSyncRun | None:
        return await self.db.scalar(
            select(ProductionAssetSyncRun).where(
                ProductionAssetSyncRun.id == run_id, *self._scope_filter()
            )
        )

    async def list_runs(
        self, *, source_key: str | None = None, limit: int = 50
    ) -> list[ProductionAssetSyncRun]:
        stmt = select(ProductionAssetSyncRun).where(*self._scope_filter())
        if source_key:
            stmt = stmt.where(ProductionAssetSyncRun.source_key == source_key)
        rows = await self.db.execute(
            stmt.order_by(ProductionAssetSyncRun.started_at.desc()).limit(max(1, min(limit, 200)))
        )
        return list(rows.scalars().all())

    async def _claim_run(
        self,
        *,
        source_key: str,
        connector_id: str | None,
        idempotency_key: str,
        input_hash: str,
        cursor_before: str | None,
        cursor_after: str | None,
        authoritative: bool,
        input_stats: dict[str, int],
    ) -> tuple[ProductionAssetSyncRun, bool]:
        now = datetime.now(UTC)
        await self._advisory_lock(source_key)
        existing = await self.db.scalar(
            select(ProductionAssetSyncRun)
            .where(
                *self._scope_filter(),
                ProductionAssetSyncRun.source_key == source_key,
                ProductionAssetSyncRun.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        if existing is not None:
            if existing.input_hash != input_hash:
                raise AssetSyncError("asset_sync_idempotency_payload_mismatch")
            if existing.status == "completed":
                return existing, False
            lease_expires_at = _aware(existing.lease_expires_at)
            if existing.status == "running" and lease_expires_at and lease_expires_at > now:
                raise AssetSyncError("asset_sync_already_running")
        active = await self.db.scalar(
            select(ProductionAssetSyncRun)
            .where(
                *self._scope_filter(),
                ProductionAssetSyncRun.source_key == source_key,
                ProductionAssetSyncRun.idempotency_key != idempotency_key,
                ProductionAssetSyncRun.status == "running",
            )
            .order_by(ProductionAssetSyncRun.started_at.desc())
            .limit(1)
            .with_for_update()
        )
        if active is not None:
            active_lease = _aware(active.lease_expires_at)
            if active_lease and active_lease > now:
                raise AssetSyncError("asset_sync_source_already_running")
            active.status = "failed"
            active.completed_at = now
            active.heartbeat_at = now
            active.error = "asset_sync_lease_expired"
        await self._validate_cursor(source_key, cursor_before, idempotency_key)
        if existing is not None:
            existing.status = "running"
            existing.attempt_count = int(existing.attempt_count or 0) + 1
            existing.lease_owner = self.lease_owner
            existing.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            existing.heartbeat_at = now
            existing.started_at = now
            existing.completed_at = None
            existing.error = None
            existing.stats = dict(input_stats)
            run = existing
        else:
            run = ProductionAssetSyncRun(
                id=str(uuid.uuid4()),
                tenant_id=self.scope.tenant_id,
                workspace_id=self.scope.workspace_id,
                source_key=source_key,
                connector_id=connector_id,
                status="running",
                idempotency_key=idempotency_key,
                input_hash=input_hash,
                cursor_before=cursor_before,
                cursor_after=cursor_after,
                authoritative=authoritative,
                attempt_count=1,
                lease_owner=self.lease_owner,
                lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                heartbeat_at=now,
                stats=dict(input_stats),
                requested_by=self.scope.user_id,
                started_at=now,
            )
            self.db.add(run)
        await self.db.flush()
        append_audit(
            self.db,
            user_id=self.scope.user_id,
            action="production_asset_sync.started",
            resource_type="production_asset_sync_run",
            resource_id=run.id,
            payload={
                "source_key": source_key,
                "connector_id": connector_id,
                "authoritative": authoritative,
                "attempt_count": run.attempt_count,
                **input_stats,
            },
        )
        await self.db.commit()
        return run, True

    async def _validate_cursor(
        self, source_key: str, cursor_before: str | None, idempotency_key: str
    ) -> None:
        latest = await self.db.scalar(
            select(ProductionAssetSyncRun)
            .where(
                *self._scope_filter(),
                ProductionAssetSyncRun.source_key == source_key,
                ProductionAssetSyncRun.status == "completed",
                ProductionAssetSyncRun.idempotency_key != idempotency_key,
            )
            .order_by(ProductionAssetSyncRun.completed_at.desc())
            .limit(1)
        )
        if latest is not None and latest.cursor_after != cursor_before:
            raise AssetSyncError("asset_sync_cursor_mismatch")

    async def run_sync(
        self,
        *,
        source_key: str,
        connector_id: str | None,
        idempotency_key: str,
        cursor_before: str | None,
        cursor_after: str | None,
        authoritative: bool,
        adopt_existing: bool,
        assets: list[dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> ProductionAssetSyncRun:
        """执行一次有界同步；该方法拥有 claim、结果和失败状态的事务提交。"""

        source_key = source_key.strip()
        idempotency_key = idempotency_key.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", source_key):
            raise AssetSyncError("asset_sync_source_key_invalid")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}", idempotency_key):
            raise AssetSyncError("asset_sync_idempotency_key_invalid")
        if any(value is not None and len(value) > 512 for value in (cursor_before, cursor_after)):
            raise AssetSyncError("asset_sync_cursor_invalid")
        if cursor_before is not None and cursor_after == cursor_before:
            raise AssetSyncError("asset_sync_cursor_not_advanced")
        if len(assets) > 500 or len(relations) > 1000 or (not assets and not authoritative):
            raise AssetSyncError("asset_sync_size_invalid")
        if relations and not assets:
            raise AssetSyncError("asset_sync_relations_require_assets")
        await self._validate_connector(connector_id)
        normalized_assets = [dict(item) for item in assets]
        if connector_id:
            for item in normalized_assets:
                declared_connector = item.get("connector_id")
                if declared_connector and declared_connector != connector_id:
                    raise AssetSyncError("asset_sync_asset_connector_mismatch")
                item["connector_id"] = connector_id
        digest = _input_hash(
            source_key=source_key,
            connector_id=connector_id,
            cursor_before=cursor_before,
            cursor_after=cursor_after,
            authoritative=authoritative,
            adopt_existing=adopt_existing,
            assets=normalized_assets,
            relations=relations,
        )
        input_stats = {
            "assets_received": len(normalized_assets),
            "relations_received": len(relations),
        }
        run, claimed = await self._claim_run(
            source_key=source_key,
            connector_id=connector_id,
            idempotency_key=idempotency_key,
            input_hash=digest,
            cursor_before=cursor_before,
            cursor_after=cursor_after,
            authoritative=authoritative,
            input_stats=input_stats,
        )
        authoritative_label = "true" if authoritative else "false"
        if not claimed:
            PRODUCTION_ASSET_SYNC_TOTAL.labels(
                status="replayed", authoritative=authoritative_label
            ).inc()
            return run

        started_monotonic = time.monotonic()
        try:
            await self._advisory_lock(source_key)
            now = datetime.now(UTC)
            result: dict[str, Any] = {
                "created_assets": 0,
                "updated_assets": 0,
                "created_relations": 0,
                "updated_relations": 0,
            }
            if normalized_assets:
                result = await AssetGraphService(self.db, self.scope).import_graph(
                    assets=normalized_assets,
                    relations=relations,
                    upsert=True,
                    source=f"asset_sync:{source_key}",
                    source_key=source_key,
                    sync_run_id=run.id,
                    observed_at=now,
                    adopt_existing=adopt_existing,
                )
            retired_assets = 0
            deleted_relations = 0
            if authoritative:
                relation_result = await self.db.execute(
                    delete(ProductionAssetRelation).where(
                        ProductionAssetRelation.tenant_id == self.scope.tenant_id,
                        ProductionAssetRelation.workspace_id == self.scope.workspace_id,
                        ProductionAssetRelation.source_key == source_key,
                        ProductionAssetRelation.last_sync_run_id.is_distinct_from(run.id),
                    )
                )
                deleted_relations = int(getattr(relation_result, "rowcount", 0) or 0)
                asset_result = await self.db.execute(
                    update(ProductionAsset)
                    .where(
                        ProductionAsset.tenant_id == self.scope.tenant_id,
                        ProductionAsset.workspace_id == self.scope.workspace_id,
                        ProductionAsset.source_key == source_key,
                        ProductionAsset.last_sync_run_id.is_distinct_from(run.id),
                        ProductionAsset.status != "retired",
                    )
                    .values(status="retired")
                )
                retired_assets = int(getattr(asset_result, "rowcount", 0) or 0)
            run = await self.db.scalar(
                select(ProductionAssetSyncRun)
                .where(ProductionAssetSyncRun.id == run.id, *self._scope_filter())
                .with_for_update()
            )
            if run is None or run.lease_owner != self.lease_owner:
                raise AssetSyncError("asset_sync_lease_lost")
            run.status = "completed"
            run.heartbeat_at = now
            run.completed_at = now
            run.error = None
            run.stats = {
                **input_stats,
                **{key: int(value) for key, value in result.items() if isinstance(value, int)},
                "retired_assets": retired_assets,
                "deleted_relations": deleted_relations,
            }
            append_audit(
                self.db,
                user_id=self.scope.user_id,
                action="production_asset_sync.completed",
                resource_type="production_asset_sync_run",
                resource_id=run.id,
                payload={"source_key": source_key, **run.stats},
            )
            await self.db.commit()
            PRODUCTION_ASSET_SYNC_TOTAL.labels(
                status="completed", authoritative=authoritative_label
            ).inc()
            PRODUCTION_ASSET_SYNC_DURATION.labels(
                status="completed", authoritative=authoritative_label
            ).observe(time.monotonic() - started_monotonic)
            return run
        except Exception as exc:
            await self.db.rollback()
            failed = await self.db.scalar(
                select(ProductionAssetSyncRun)
                .where(ProductionAssetSyncRun.id == run.id, *self._scope_filter())
                .with_for_update()
            )
            if failed is not None and failed.lease_owner == self.lease_owner:
                now = datetime.now(UTC)
                failed.status = "failed"
                failed.heartbeat_at = now
                failed.completed_at = now
                failed.error = (
                    str(exc)[:2000]
                    if isinstance(exc, AssetGraphError | AssetSyncError)
                    else f"asset_sync_internal_error:{type(exc).__name__}"
                )
                append_audit(
                    self.db,
                    user_id=self.scope.user_id,
                    action="production_asset_sync.failed",
                    resource_type="production_asset_sync_run",
                    resource_id=failed.id,
                    payload={"source_key": source_key, "error": failed.error},
                )
                await self.db.commit()
            PRODUCTION_ASSET_SYNC_TOTAL.labels(
                status="failed", authoritative=authoritative_label
            ).inc()
            PRODUCTION_ASSET_SYNC_DURATION.labels(
                status="failed", authoritative=authoritative_label
            ).observe(time.monotonic() - started_monotonic)
            raise
