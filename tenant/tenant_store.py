"""Optional Postgres persistence for tenant records (skeleton)."""

from __future__ import annotations

from typing import Any

from tenant.tenant_manager import TenantManager, TenantRecord


async def upsert_tenant_record(record: TenantRecord) -> None:
    """Persist tenant when DB models exist; always register in-process."""
    TenantManager().register(record)
    try:
        from infra.storage.database import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            try:
                from infra.config.settings import settings
                from tenant.tenant_rls import set_session_tenant

                if bool(getattr(settings, "enterprise_tenant_rls_enabled", False)):
                    await set_session_tenant(db, record.tenant_id)
            except Exception:
                pass
            await db.execute(
                text(
                    """
                    INSERT INTO tenants (tenant_id, name, tier, data_residency, metadata_json)
                    VALUES (:tid, :name, :tier, :residency, :meta)
                    ON CONFLICT (tenant_id) DO UPDATE SET
                      name = EXCLUDED.name,
                      tier = EXCLUDED.tier,
                      data_residency = EXCLUDED.data_residency
                    """
                ),
                {
                    "tid": record.tenant_id,
                    "name": record.name or record.tenant_id,
                    "tier": record.tier,
                    "residency": record.data_residency,
                    "meta": "{}",
                },
            )
            await db.commit()
    except Exception:
        pass


async def load_tenant(tenant_id: str) -> dict[str, Any] | None:
    rec = TenantManager().get(tenant_id)
    if rec:
        return rec.to_dict()
    return None