"""在隔离 PostgreSQL 数据库验证企业目录、成员和知识 ACL 投影。"""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from infra.storage.database import AsyncSessionLocal
from infra.storage.models import (
    EnterpriseDirectoryMembership,
    EnterpriseDirectoryPrincipal,
    EnterpriseDirectorySyncRun,
    KnowledgePrincipalMembership,
    User,
)
from services.enterprise_directory import sync_enterprise_directory
from services.enterprise_operations import enterprise_operations_overview


def _assert_isolated_database() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    database_name = urlparse(database_url.replace("postgresql+asyncpg", "postgresql")).path.strip(
        "/"
    )
    if not any(marker in database_name.lower() for marker in ("test", "verify", "temp")):
        raise RuntimeError("企业目录验收只允许在名称包含 test/verify/temp 的隔离数据库运行")


async def _verify() -> None:
    _assert_isolated_database()
    suffix = uuid.uuid4().hex[:8]
    admin = User(
        id=str(uuid.uuid4()),
        email=f"directory-admin-{suffix}@example.com",
        display_name="Directory Admin",
        status="active",
        role="admin",
        is_active=True,
    )
    member = User(
        id=str(uuid.uuid4()),
        email=f"directory-member-{suffix}@example.com",
        display_name="Directory Member",
        status="active",
        role="user",
        is_active=True,
    )
    async with AsyncSessionLocal() as db:
        db.add_all([admin, member])
        await db.flush()
        run = await sync_enterprise_directory(
            db,
            tenant_id="tenant-verify",
            workspace_id="workspace-verify",
            actor=admin,
            provider="scim",
            cursor="cursor-1",
            authoritative=True,
            principals=[
                {
                    "principal_type": "department",
                    "external_id": "finance",
                    "display_name": "财务部",
                    "attributes": {"cost_center": "FIN"},
                },
                {
                    "principal_type": "role",
                    "external_id": "finance-reviewer",
                    "display_name": "财务审核岗",
                },
            ],
            memberships=[
                {
                    "user_email": member.email,
                    "principal_type": "department",
                    "principal_external_id": "finance",
                    "status": "active",
                    "metadata": {"employee_id": f"E-{suffix}"},
                }
            ],
        )
        await db.commit()
        assert run.status == "completed"
        assert run.stats["principals_created"] == 2
        assert run.stats["memberships_created"] == 1
        principal = await db.scalar(
            select(EnterpriseDirectoryPrincipal).where(
                EnterpriseDirectoryPrincipal.tenant_id == "tenant-verify",
                EnterpriseDirectoryPrincipal.workspace_id == "workspace-verify",
                EnterpriseDirectoryPrincipal.external_id == "finance",
            )
        )
        assert principal is not None and principal.display_name == "财务部"
        membership = await db.scalar(
            select(EnterpriseDirectoryMembership).where(
                EnterpriseDirectoryMembership.user_id == member.id,
                EnterpriseDirectoryMembership.principal_id == principal.id,
            )
        )
        assert membership is not None and membership.status == "active"
        knowledge_membership = await db.scalar(
            select(KnowledgePrincipalMembership).where(
                KnowledgePrincipalMembership.tenant_id == "tenant-verify",
                KnowledgePrincipalMembership.workspace_id == "workspace-verify",
                KnowledgePrincipalMembership.user_id == member.id,
                KnowledgePrincipalMembership.principal_type == "department",
                KnowledgePrincipalMembership.principal_id == "finance",
            )
        )
        assert knowledge_membership is not None
        assert knowledge_membership.source == "scim"
        assert knowledge_membership.membership_metadata["directory_principal_id"] == principal.id
        other_scope = await db.scalar(
            select(EnterpriseDirectoryPrincipal).where(
                EnterpriseDirectoryPrincipal.tenant_id == "tenant-other"
            )
        )
        assert other_scope is None
        sync_run = await db.scalar(
            select(EnterpriseDirectorySyncRun).where(EnterpriseDirectorySyncRun.id == run.id)
        )
        assert sync_run is not None and sync_run.cursor == "cursor-1"
        overview = await enterprise_operations_overview(
            db, tenant_id="tenant-verify", workspace_id="workspace-verify"
        )
        assert overview["directory"]["principals"] == 2
        assert overview["directory"]["memberships"] == 1

        idempotent = await sync_enterprise_directory(
            db,
            tenant_id="tenant-verify",
            workspace_id="workspace-verify",
            actor=admin,
            provider="scim",
            cursor="cursor-2",
            authoritative=True,
            principals=[
                {
                    "principal_type": "department",
                    "external_id": "finance",
                    "display_name": "财务中心",
                },
                {
                    "principal_type": "role",
                    "external_id": "finance-reviewer",
                    "display_name": "财务审核岗",
                },
            ],
            memberships=[
                {
                    "user_email": member.email,
                    "principal_type": "department",
                    "principal_external_id": "finance",
                    "status": "active",
                }
            ],
        )
        await db.commit()
        assert idempotent.stats["principals_created"] == 0
        assert idempotent.stats["memberships_created"] == 0
        assert idempotent.stats["principals_updated"] == 2

        retired = await sync_enterprise_directory(
            db,
            tenant_id="tenant-verify",
            workspace_id="workspace-verify",
            actor=admin,
            provider="scim",
            cursor="cursor-3",
            authoritative=True,
            principals=[],
            memberships=[],
        )
        await db.commit()
        assert retired.stats["principals_deactivated"] == 2
        assert retired.stats["memberships_deactivated"] == 1
        await db.refresh(knowledge_membership)
        assert knowledge_membership.status == "inactive"
    print("企业目录与运营中心 PostgreSQL 验收通过")


if __name__ == "__main__":
    asyncio.run(_verify())
