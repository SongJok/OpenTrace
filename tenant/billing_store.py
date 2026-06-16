"""Persist billing ledger rows and invoice snapshots (Postgres)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from infra.observability.logger import get_logger
from tenant.billing_manager import CostAttribution
from tenant.tenant_context import TenantContext

logger = get_logger(__name__)


async def persist_ledger_entry(
    ctx: TenantContext,
    attr: CostAttribution,
    *,
    session_id: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    metadata: dict[str, Any] | None = None,
) -> bool:
    try:
        from infra.storage.database import AsyncSessionLocal
        from sqlalchemy import text

        meta = dict(metadata or {})
        async with AsyncSessionLocal() as db:
            try:
                from infra.config.settings import settings
                from tenant.tenant_rls import set_session_tenant

                if bool(getattr(settings, "enterprise_tenant_rls_enabled", False)):
                    await set_session_tenant(db, ctx.tenant_id)
            except Exception:
                pass
            await db.execute(
                text(
                    """
                    INSERT INTO billing_ledger (
                        tenant_id, org_id, workspace_id, session_id, goal_id,
                        capability_type, cost_usd, prompt_tokens, completion_tokens,
                        currency, metadata_json
                    ) VALUES (
                        :tenant_id, :org_id, :workspace_id, :session_id, :goal_id,
                        :capability_type, :cost_usd, :prompt_tokens, :completion_tokens,
                        :currency, :metadata_json
                    )
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "org_id": ctx.org_id or None,
                    "workspace_id": ctx.workspace_id or None,
                    "session_id": session_id or None,
                    "goal_id": attr.goal_id or ctx.goal_id or None,
                    "capability_type": attr.capability_type or None,
                    "cost_usd": float(attr.cost),
                    "prompt_tokens": int(prompt_tokens),
                    "completion_tokens": int(completion_tokens),
                    "currency": attr.currency,
                    "metadata_json": json.dumps(meta, ensure_ascii=False),
                },
            )
            await db.commit()
        return True
    except Exception as exc:
        logger.debug("billing_ledger_persist_skipped", error=str(exc))
        return False


async def persist_invoice_snapshot(
    tenant_id: str,
    *,
    period_start: datetime,
    period_end: datetime,
    total_usd: float,
    line_items: list[dict[str, Any]],
    status: str = "draft",
) -> str | None:
    invoice_id = f"inv_{uuid.uuid4().hex[:16]}"
    try:
        from infra.storage.database import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO billing_invoices (
                        invoice_id, tenant_id, period_start, period_end,
                        total_usd, status, line_items_json
                    ) VALUES (
                        :invoice_id, :tenant_id, :period_start, :period_end,
                        :total_usd, :status, :line_items_json
                    )
                    """
                ),
                {
                    "invoice_id": invoice_id,
                    "tenant_id": tenant_id,
                    "period_start": period_start,
                    "period_end": period_end,
                    "total_usd": float(total_usd),
                    "status": status,
                    "line_items_json": json.dumps(line_items, ensure_ascii=False),
                },
            )
            await db.commit()
        return invoice_id
    except Exception as exc:
        logger.debug("billing_invoice_persist_skipped", error=str(exc))
        return None


def snapshot_to_invoice_lines(
    snapshot: dict[str, Any],
    *,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """Convert BillingManager.snapshot dict to invoice line items."""
    lines: list[dict[str, Any]] = [
        {
            "type": "tenant_total",
            "tenant_id": tenant_id,
            "amount_usd": float(snapshot.get("total_cost") or 0.0),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    ]
    by_cap = snapshot.get("by_capability") or {}
    if isinstance(by_cap, dict):
        for cap, amt in by_cap.items():
            lines.append(
                {
                    "type": "capability",
                    "capability_type": cap,
                    "amount_usd": float(amt or 0.0),
                }
            )
    return lines