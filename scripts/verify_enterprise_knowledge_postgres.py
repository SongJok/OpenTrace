#!/usr/bin/env python3
"""在一次性 PostgreSQL 库验证企业知识空间 ACL、密级和发布生命周期。"""

from __future__ import annotations

import asyncio
import os
import uuid
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from infra.storage.models import (
    KnowledgePrincipalMembership,
    KnowledgeReviewTask,
    KnowledgeSource,
    KnowledgeSourcePermission,
    KnowledgeSourceVersion,
    KnowledgeSpace,
    KnowledgeSpaceMember,
    User,
)
from knowledge.access import accessible_source_predicate, resolve_access_context
from knowledge.lifecycle import publish_source_version
from knowledge.trace import trace_knowledge_assets


def _database_url() -> str:
    raw = os.environ.get("ENTERPRISE_KNOWLEDGE_TEST_DATABASE_URL", "")
    if "migration_test" not in urlsplit(raw).path:
        raise SystemExit(
            "ENTERPRISE_KNOWLEDGE_TEST_DATABASE_URL 必须指向一次性 migration_test 数据库"
        )
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw


async def verify() -> None:
    engine = create_async_engine(_database_url())
    marker = uuid.uuid4().hex[:12]
    owner = User(
        id=f"kb-owner-{marker}",
        email=f"kb-owner-{marker}@example.com",
        display_name="KB Owner",
        status="active",
        role="admin",
        is_active=True,
    )
    employee = User(
        id=f"kb-user-{marker}",
        email=f"kb-user-{marker}@example.com",
        display_name="KB User",
        status="active",
        role="user",
        is_active=True,
    )
    outsider = User(
        id=f"kb-outsider-{marker}",
        email=f"kb-outsider-{marker}@example.com",
        display_name="KB Outsider",
        status="active",
        role="user",
        is_active=True,
    )
    async with AsyncSession(engine, expire_on_commit=False) as db:
        transaction = await db.begin()
        try:
            db.add_all([owner, employee, outsider])
            await db.flush()
            space = KnowledgeSpace(
                id=f"kb-space-{marker}",
                tenant_id="kb-tenant",
                workspace_id="kb-workspace",
                owner_id=owner.id,
                name="财务制度",
                slug=f"finance-{marker}",
                space_type="department",
                visibility="members",
                default_classification="confidential",
                publish_policy="review",
            )
            db.add(space)
            await db.flush()
            db.add_all(
                [
                    KnowledgeSpaceMember(
                        id=f"kb-member-{marker}",
                        space_id=space.id,
                        tenant_id="kb-tenant",
                        workspace_id="kb-workspace",
                        subject_type="department",
                        subject_id="finance",
                        role="publisher",
                        granted_by=owner.id,
                    ),
                    KnowledgePrincipalMembership(
                        id=f"kb-principal-{marker}",
                        tenant_id="kb-tenant",
                        workspace_id="kb-workspace",
                        user_id=employee.id,
                        principal_type="department",
                        principal_id="finance",
                        source="scim",
                        status="active",
                    ),
                    KnowledgePrincipalMembership(
                        id=f"kb-clearance-{marker}",
                        tenant_id="kb-tenant",
                        workspace_id="kb-workspace",
                        user_id=employee.id,
                        principal_type="clearance",
                        principal_id="confidential",
                        source="hr",
                        status="active",
                    ),
                ]
            )
            await db.flush()
            source = KnowledgeSource(
                id=f"kb-source-{marker}",
                owner_id=owner.id,
                tenant_id="kb-tenant",
                workspace_id="kb-workspace",
                space_id=space.id,
                source_type="sharepoint",
                external_ref=f"sharepoint:policy-{marker}",
                title="差旅报销制度",
                content_hash=marker.ljust(64, "0"),
                authority="official",
                classification="confidential",
                source_system="sharepoint",
                sync_status="current",
                status="review",
            )
            db.add(source)
            await db.flush()
            db.add(
                KnowledgeSourcePermission(
                    id=f"kb-acl-{marker}",
                    source_id=source.id,
                    tenant_id="kb-tenant",
                    workspace_id="kb-workspace",
                    subject_type="department",
                    subject_id="finance",
                    permission="view",
                    inherited=True,
                )
            )
            version = KnowledgeSourceVersion(
                id=f"kb-version-{marker}",
                source_id=source.id,
                version_number=1,
                content_hash=source.content_hash,
                compiler_version="knowledge_compiler_v1",
                status="review",
            )
            db.add(version)
            await db.flush()
            db.add(
                KnowledgeReviewTask(
                    id=f"kb-review-{marker}",
                    source_version_id=version.id,
                    space_id=space.id,
                    tenant_id="kb-tenant",
                    workspace_id="kb-workspace",
                    status="pending",
                    required_role="publisher",
                    requested_by=owner.id,
                )
            )
            await db.flush()

            employee_context = await resolve_access_context(
                db,
                user=employee,
                tenant_id="kb-tenant",
                workspace_id="kb-workspace",
            )
            assert employee_context.space_roles[space.id] == "publisher"
            assert employee_context.clearance == "confidential"
            visible = list(
                (
                    await db.execute(
                        select(KnowledgeSource).where(accessible_source_predicate(employee_context))
                    )
                ).scalars()
            )
            assert source.id in {row.id for row in visible}

            outsider_context = await resolve_access_context(
                db,
                user=outsider,
                tenant_id="kb-tenant",
                workspace_id="kb-workspace",
            )
            hidden = list(
                (
                    await db.execute(
                        select(KnowledgeSource).where(accessible_source_predicate(outsider_context))
                    )
                ).scalars()
            )
            assert source.id not in {row.id for row in hidden}

            await publish_source_version(
                db,
                source_version_id=version.id,
                decided_by=employee.id,
                comment="数据库级企业知识发布验收",
            )
            assert source.status == "published"
            assert source.active_version_id == version.id
            review = await db.get(KnowledgeReviewTask, f"kb-review-{marker}")
            assert review is not None and review.status == "approved"
            employee_trace = await trace_knowledge_assets(
                db,
                ids=[source.id],
                tenant_id="kb-tenant",
                workspace_id="kb-workspace",
                owner_id=employee.id,
            )
            outsider_trace = await trace_knowledge_assets(
                db,
                ids=[source.id],
                tenant_id="kb-tenant",
                workspace_id="kb-workspace",
                owner_id=outsider.id,
            )
            assert employee_trace and employee_trace[0]["classification"] == "confidential"
            assert outsider_trace == []
            print("OK: enterprise knowledge ACL, classification, trace and review lifecycle")
        finally:
            await transaction.rollback()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(verify())
