"""Reusable ownership and tenant predicates for API resources."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import DataSource, Document


def normalized_tenant_scope(metadata: dict[str, Any] | None) -> tuple[str, str]:
    md = metadata or {}
    tenant_id = str(md.get("tenant_id") or "default").strip() or "default"
    workspace_id = str(md.get("workspace_id") or "default").strip() or "default"
    return tenant_id, workspace_id


def scoped_documents_statement(
    *,
    user_id: str,
    tenant_metadata: dict[str, Any] | None,
    document_id: str | None = None,
) -> Select:
    tenant_id, workspace_id = normalized_tenant_scope(tenant_metadata)
    stmt = select(Document).where(
        Document.owner_id == user_id,
        Document.tenant_id == tenant_id,
        Document.workspace_id == workspace_id,
    )
    if document_id:
        stmt = stmt.where(Document.id == document_id)
    return stmt


def owned_data_sources_statement(
    *,
    user_id: str,
    tenant_metadata: dict[str, Any] | None = None,
    data_source_id: str | None = None,
    active_only: bool = False,
) -> Select:
    tenant_id, workspace_id = normalized_tenant_scope(tenant_metadata)
    stmt = select(DataSource).where(
        DataSource.user_id == user_id,
        DataSource.tenant_id == tenant_id,
        DataSource.workspace_id == workspace_id,
    )
    if data_source_id:
        stmt = stmt.where(DataSource.id == data_source_id)
    if active_only:
        stmt = stmt.where(DataSource.status == "active")
    return stmt


async def get_owned_data_source(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_metadata: dict[str, Any] | None = None,
    data_source_id: str,
) -> DataSource | None:
    result = await db.execute(
        owned_data_sources_statement(
            user_id=user_id,
            tenant_metadata=tenant_metadata,
            data_source_id=data_source_id,
        )
    )
    return result.scalar_one_or_none()
