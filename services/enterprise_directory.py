"""企业目录同步与知识权限主体投影。"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    AuditLog,
    EnterpriseDirectoryMembership,
    EnterpriseDirectoryPrincipal,
    EnterpriseDirectorySyncRun,
    KnowledgePrincipalMembership,
    User,
)

ALLOWED_PRINCIPAL_TYPES = {"department", "group", "role"}
ALLOWED_PROVIDERS = {"manual", "scim", "hr"}


def directory_principal_payload(row: EnterpriseDirectoryPrincipal) -> dict[str, Any]:
    return {
        "id": row.id,
        "principal_type": row.principal_type,
        "external_id": row.external_id,
        "display_name": row.display_name,
        "parent_external_id": row.parent_external_id,
        "source": row.source,
        "status": row.status,
        "attributes": dict(row.attributes or {}),
        "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def directory_membership_payload(
    row: EnterpriseDirectoryMembership,
    *,
    user: User | None = None,
    principal: EnterpriseDirectoryPrincipal | None = None,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "user_email": user.email if user else None,
        "display_name": user.display_name if user else None,
        "principal_id": row.principal_id,
        "principal_type": principal.principal_type if principal else None,
        "principal_external_id": principal.external_id if principal else None,
        "principal_name": principal.display_name if principal else None,
        "source": row.source,
        "status": row.status,
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "metadata": dict(row.membership_metadata or {}),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def directory_sync_run_payload(row: EnterpriseDirectorySyncRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "status": row.status,
        "cursor": row.cursor,
        "authoritative": row.authoritative,
        "stats": dict(row.stats or {}),
        "requested_by": row.requested_by,
        "error": row.error,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


async def sync_enterprise_directory(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    actor: User,
    provider: str,
    cursor: str | None,
    authoritative: bool,
    principals: list[dict[str, Any]],
    memberships: list[dict[str, Any]],
) -> EnterpriseDirectorySyncRun:
    """串行同步目录，并将成员关系投影到知识 ACL 主体映射。"""

    if provider not in ALLOWED_PROVIDERS:
        raise ValueError("unsupported_directory_provider")
    now = datetime.now(UTC)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:scope_key))"),
        {"scope_key": f"enterprise_directory:{tenant_id}:{workspace_id}:{provider}"},
    )
    run = EnterpriseDirectorySyncRun(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        provider=provider,
        status="running",
        cursor=cursor,
        authoritative=authoritative,
        requested_by=actor.id,
        stats={},
        started_at=now,
    )
    db.add(run)
    await db.flush()

    stats = {
        "principals_created": 0,
        "principals_updated": 0,
        "principals_deactivated": 0,
        "memberships_created": 0,
        "memberships_updated": 0,
        "memberships_deactivated": 0,
        "knowledge_memberships_synced": 0,
        "unresolved_users": 0,
        "unresolved_principals": 0,
    }
    existing_principals = list(
        (
            await db.execute(
                select(EnterpriseDirectoryPrincipal).where(
                    EnterpriseDirectoryPrincipal.tenant_id == tenant_id,
                    EnterpriseDirectoryPrincipal.workspace_id == workspace_id,
                )
            )
        ).scalars()
    )
    principal_map = {(row.principal_type, row.external_id): row for row in existing_principals}
    incoming_principal_keys: set[tuple[str, str]] = set()
    for item in principals:
        principal_type = str(item.get("principal_type") or "").strip().lower()
        external_id = str(item.get("external_id") or "").strip()
        if principal_type not in ALLOWED_PRINCIPAL_TYPES or not external_id:
            continue
        key = (principal_type, external_id)
        incoming_principal_keys.add(key)
        row = principal_map.get(key)
        if row is None:
            row = EnterpriseDirectoryPrincipal(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                principal_type=principal_type,
                external_id=external_id,
                display_name=str(item.get("display_name") or external_id).strip() or external_id,
                source=provider,
            )
            db.add(row)
            principal_map[key] = row
            stats["principals_created"] += 1
        else:
            stats["principals_updated"] += 1
        row.display_name = str(item.get("display_name") or external_id).strip() or external_id
        row.parent_external_id = str(item.get("parent_external_id") or "").strip() or None
        row.source = provider
        row.status = str(item.get("status") or "active").strip().lower()
        if row.status not in {"active", "inactive"}:
            row.status = "active"
        row.attributes = dict(item.get("attributes") or {})
        row.last_synced_at = now

    if authoritative:
        for row in existing_principals:
            key = (row.principal_type, row.external_id)
            if (
                row.source == provider
                and key not in incoming_principal_keys
                and row.status != "inactive"
            ):
                row.status = "inactive"
                row.last_synced_at = now
                stats["principals_deactivated"] += 1
    await db.flush()

    requested_emails = {
        str(item.get("user_email") or "").strip().lower()
        for item in memberships
        if str(item.get("user_email") or "").strip()
    }
    users = list(
        (
            await db.execute(
                select(User).where(
                    func.lower(User.email).in_(requested_emails),
                    User.status == "active",
                    User.is_active.is_(True),
                )
                if requested_emails
                else select(User).where(User.id == "")
            )
        ).scalars()
    )
    user_map = {row.email.strip().lower(): row for row in users}
    existing_memberships = list(
        (
            await db.execute(
                select(EnterpriseDirectoryMembership).where(
                    EnterpriseDirectoryMembership.tenant_id == tenant_id,
                    EnterpriseDirectoryMembership.workspace_id == workspace_id,
                )
            )
        ).scalars()
    )
    membership_map = {(row.user_id, row.principal_id): row for row in existing_memberships}
    knowledge_rows = list(
        (
            await db.execute(
                select(KnowledgePrincipalMembership).where(
                    KnowledgePrincipalMembership.tenant_id == tenant_id,
                    KnowledgePrincipalMembership.workspace_id == workspace_id,
                )
            )
        ).scalars()
    )
    knowledge_map = {
        (row.user_id, row.principal_type, row.principal_id): row for row in knowledge_rows
    }
    incoming_membership_keys: set[tuple[str, str]] = set()
    for item in memberships:
        email = str(item.get("user_email") or "").strip().lower()
        user = user_map.get(email)
        if user is None:
            stats["unresolved_users"] += 1
            continue
        principal_type = str(item.get("principal_type") or "").strip().lower()
        external_id = str(item.get("principal_external_id") or "").strip()
        principal = principal_map.get((principal_type, external_id))
        if principal is None:
            stats["unresolved_principals"] += 1
            continue
        key = (user.id, principal.id)
        incoming_membership_keys.add(key)
        row = membership_map.get(key)
        if row is None:
            row = EnterpriseDirectoryMembership(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                user_id=user.id,
                principal_id=principal.id,
                source=provider,
            )
            db.add(row)
            membership_map[key] = row
            stats["memberships_created"] += 1
        else:
            stats["memberships_updated"] += 1
        row.source = provider
        row.status = str(item.get("status") or "active").strip().lower()
        if row.status not in {"active", "inactive"}:
            row.status = "active"
        row.effective_from = item.get("effective_from")
        row.effective_to = item.get("effective_to")
        row.membership_metadata = dict(item.get("metadata") or {})

        knowledge_key = (user.id, principal.principal_type, principal.external_id)
        knowledge = knowledge_map.get(knowledge_key)
        if knowledge is None:
            knowledge = KnowledgePrincipalMembership(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                user_id=user.id,
                principal_type=principal.principal_type,
                principal_id=principal.external_id,
                source=provider,
            )
            db.add(knowledge)
            knowledge_map[knowledge_key] = knowledge
        knowledge.source = provider
        knowledge.status = row.status
        knowledge.effective_from = row.effective_from
        knowledge.effective_to = row.effective_to
        knowledge.membership_metadata = {
            **dict(row.membership_metadata or {}),
            "directory_principal_id": principal.id,
            "directory_membership_id": row.id,
            "display_name": principal.display_name,
        }
        stats["knowledge_memberships_synced"] += 1

    if authoritative:
        for row in existing_memberships:
            if (
                row.source != provider
                or (row.user_id, row.principal_id) in incoming_membership_keys
            ):
                continue
            if row.status != "inactive":
                row.status = "inactive"
                row.effective_to = now
                stats["memberships_deactivated"] += 1
            principal = next(
                (item for item in existing_principals if item.id == row.principal_id), None
            )
            if principal is None:
                continue
            knowledge = knowledge_map.get(
                (row.user_id, principal.principal_type, principal.external_id)
            )
            if knowledge is not None and knowledge.source == provider:
                knowledge.status = "inactive"
                knowledge.effective_to = now

    run.status = "completed"
    run.stats = stats
    run.completed_at = now
    db.add(
        AuditLog(
            id=str(uuid.uuid4()),
            user_id=actor.id,
            action="enterprise_directory_sync",
            resource_type="enterprise_directory",
            resource_id=run.id,
            payload_json=json.dumps(
                {
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "provider": provider,
                    "authoritative": authoritative,
                    "stats": stats,
                },
                ensure_ascii=False,
            ),
        )
    )
    await db.flush()
    return run
