"""企业知识库空间、权限、连接器同步和发布治理 API。"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.audit.logger import write_audit_log
from infra.errors import AppException, ErrorCodes
from infra.security.resource_scope import normalized_tenant_scope
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    KnowledgeConnector,
    KnowledgePage,
    KnowledgePrincipalMembership,
    KnowledgeReviewTask,
    KnowledgeSource,
    KnowledgeSourceVersion,
    KnowledgeSpace,
    KnowledgeSpaceMember,
    KnowledgeSpaceProject,
    KnowledgeSyncItem,
    KnowledgeSyncRun,
    Project,
    User,
)
from knowledge.access import (
    accessible_source_predicate,
    classification_allows,
    require_space_role,
    resolve_access_context,
    role_allows,
)
from knowledge.compiler import content_hash
from knowledge.lifecycle import (
    publish_source_version,
    reject_source_version,
    reopen_due_review_tasks,
    withdraw_source,
)
from knowledge.query import search_knowledge
from knowledge.sync import retry_sync_run

router = APIRouter()

SpaceType = Literal["company", "department", "role", "project", "personal"]
SpaceRole = Literal["viewer", "contributor", "reviewer", "publisher", "admin"]
Classification = Literal["public", "internal", "confidential", "restricted"]
SubjectType = Literal["user", "department", "group", "role", "project"]


class KnowledgeSpaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=128)
    description: str = Field(default="", max_length=4000)
    space_type: SpaceType = "project"
    visibility: Literal["private", "members", "tenant"] = "members"
    default_classification: Classification = "internal"
    publish_policy: Literal["auto", "review"] = "review"
    review_cycle_days: int = Field(default=180, ge=1, le=3650)
    metadata: dict = Field(default_factory=dict)


class KnowledgeSpaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    visibility: Literal["private", "members", "tenant"] | None = None
    default_classification: Classification | None = None
    publish_policy: Literal["auto", "review"] | None = None
    review_cycle_days: int | None = Field(default=None, ge=1, le=3650)
    status: Literal["active", "archived"] | None = None


class SpaceMemberGrant(BaseModel):
    subject_type: SubjectType
    subject_id: str = Field(min_length=1, max_length=128)
    role: SpaceRole = "viewer"
    expires_at: datetime | None = None


class PrincipalMembershipUpsert(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    principal_type: Literal["department", "group", "role", "clearance"]
    principal_id: str = Field(min_length=1, max_length=128)
    source: Literal["manual", "scim", "hr"] = "manual"
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    metadata: dict = Field(default_factory=dict)


class ConnectorCreate(BaseModel):
    space_id: str
    name: str = Field(min_length=1, max_length=128)
    connector_type: Literal["push", "sharepoint", "confluence", "dingtalk", "git"] = "push"
    base_url: HttpUrl | None = None
    credential_ref: str | None = Field(default=None, max_length=255)
    sync_interval_seconds: int = Field(default=900, ge=60, le=86400)
    config: dict = Field(default_factory=dict)


class SourceAclEntry(BaseModel):
    subject_type: SubjectType
    subject_id: str = Field(min_length=1, max_length=128)
    permission: Literal["view", "edit", "admin"] = "view"
    inherited: bool = False
    external_ref: str | None = Field(default=None, max_length=512)
    expires_at: datetime | None = None


class ConnectorSnapshot(BaseModel):
    external_id: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(default="", max_length=2_000_000)
    content_type: str = Field(default="text", max_length=20)
    deleted: bool = False
    authority: str = Field(default="external", max_length=32)
    classification: Classification | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    metadata: dict = Field(default_factory=dict)
    acl: list[SourceAclEntry] = Field(default_factory=list, max_length=1000)


class ConnectorPushRequest(BaseModel):
    cursor: str | None = None
    snapshots: list[ConnectorSnapshot] = Field(min_length=1, max_length=200)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    project_id: str | None = None
    space_id: str | None = None
    top_k: int = Field(default=8, ge=1, le=50)


class ReviewDecision(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=4000)


class WithdrawRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value.lower()).strip("-")
    return normalized[:128] or f"space-{uuid.uuid4().hex[:8]}"


def _scope(request: Request, user: User) -> tuple[str, str]:
    return normalized_tenant_scope(build_tenant_metadata(request, user_id=user.id))


async def _space_or_error(
    db: AsyncSession,
    *,
    request: Request,
    user: User,
    space_id: str,
    role: str,
) -> tuple[KnowledgeSpace, str, str]:
    tenant_id, workspace_id = _scope(request, user)
    try:
        space, _ = await require_space_role(
            db,
            user=user,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            space_id=space_id,
            required_role=role,
        )
    except PermissionError as exc:
        raise AppException(ErrorCodes.PERMISSION_DENIED.code, message=str(exc)) from exc
    return space, tenant_id, workspace_id


@router.get("/knowledge/spaces")
async def list_spaces(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = _scope(request, current_user)
    context = await resolve_access_context(
        db,
        user=current_user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if not context.accessible_space_ids:
        return {"items": []}
    spaces = list(
        (
            await db.execute(
                select(KnowledgeSpace)
                .where(KnowledgeSpace.id.in_(context.accessible_space_ids))
                .order_by(KnowledgeSpace.name)
            )
        ).scalars()
    )
    return {
        "items": [
            {
                "id": row.id,
                "name": row.name,
                "slug": row.slug,
                "description": row.description,
                "space_type": row.space_type,
                "visibility": row.visibility,
                "classification": row.default_classification,
                "publish_policy": row.publish_policy,
                "review_cycle_days": row.review_cycle_days,
                "status": row.status,
                "role": context.space_roles[row.id],
                "metadata": row.space_metadata,
            }
            for row in spaces
        ]
    }


@router.post("/knowledge/search")
async def enterprise_knowledge_search(
    payload: KnowledgeSearchRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = _scope(request, current_user)
    if payload.space_id:
        await _space_or_error(
            db,
            request=request,
            user=current_user,
            space_id=payload.space_id,
            role="viewer",
        )
    items = await search_knowledge(
        query=payload.query,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=payload.project_id,
        space_id=payload.space_id,
        top_k=payload.top_k,
    )
    return {"items": items, "count": len(items)}


@router.get("/knowledge/spaces/{space_id}/sources")
async def list_space_sources(
    space_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, tenant_id, workspace_id = await _space_or_error(
        db, request=request, user=current_user, space_id=space_id, role="viewer"
    )
    context = await resolve_access_context(
        db, user=current_user, tenant_id=tenant_id, workspace_id=workspace_id
    )
    source_access = accessible_source_predicate(context)
    rows = list(
        (
            await db.execute(
                select(KnowledgeSource)
                .where(
                    KnowledgeSource.space_id == space_id,
                    KnowledgeSource.tenant_id == tenant_id,
                    KnowledgeSource.workspace_id == workspace_id,
                    source_access,
                )
                .order_by(KnowledgeSource.updated_at.desc())
            )
        ).scalars()
    )
    return {
        "items": [
            {
                "id": row.id,
                "title": row.title,
                "source_type": row.source_type,
                "source_system": row.source_system,
                "classification": row.classification,
                "authority": row.authority,
                "status": row.status,
                "sync_status": row.sync_status,
                "active_version_id": row.active_version_id,
                "effective_from": row.effective_from.isoformat() if row.effective_from else None,
                "effective_to": row.effective_to.isoformat() if row.effective_to else None,
                "review_due_at": row.review_due_at.isoformat() if row.review_due_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ]
    }


@router.get("/knowledge/spaces/{space_id}/assets")
async def list_space_assets(
    space_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, tenant_id, workspace_id = await _space_or_error(
        db, request=request, user=current_user, space_id=space_id, role="viewer"
    )
    context = await resolve_access_context(
        db, user=current_user, tenant_id=tenant_id, workspace_id=workspace_id
    )
    source_access = accessible_source_predicate(context)
    rows = (
        await db.execute(
            select(KnowledgePage, KnowledgeSource, KnowledgeSourceVersion)
            .join(
                KnowledgeSourceVersion,
                KnowledgePage.source_version_id == KnowledgeSourceVersion.id,
            )
            .join(KnowledgeSource, KnowledgeSourceVersion.source_id == KnowledgeSource.id)
            .where(
                KnowledgeSource.space_id == space_id,
                KnowledgeSource.tenant_id == tenant_id,
                KnowledgeSource.workspace_id == workspace_id,
                source_access,
                KnowledgeSource.status == "published",
                KnowledgeSource.active_version_id == KnowledgeSourceVersion.id,
                KnowledgePage.status == "published",
            )
            .order_by(KnowledgePage.title)
            .limit(500)
        )
    ).all()
    return {
        "items": [
            {
                "id": page.id,
                "source_id": source.id,
                "source_version_id": version.id,
                "title": page.title,
                "page_type": page.page_type,
                "summary": page.summary,
                "authority": page.authority,
                "confidence": page.confidence,
                "classification": source.classification,
                "review_due_at": source.review_due_at.isoformat() if source.review_due_at else None,
            }
            for page, source, version in rows
        ]
    }


@router.post("/knowledge/spaces")
async def create_space(
    payload: KnowledgeSpaceCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = _scope(request, current_user)
    if not current_user.is_superuser and (
        payload.space_type not in {"personal", "project"} or payload.visibility == "tenant"
    ):
        raise AppException(
            ErrorCodes.PERMISSION_DENIED.code,
            message="Company/department/role or tenant-visible spaces require admin permission",
        )
    slug = _slug(payload.slug or payload.name)
    existing = await db.scalar(
        select(KnowledgeSpace.id).where(
            KnowledgeSpace.tenant_id == tenant_id,
            KnowledgeSpace.workspace_id == workspace_id,
            KnowledgeSpace.slug == slug,
        )
    )
    if existing:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code, message="Knowledge space slug already exists"
        )
    row = KnowledgeSpace(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        owner_id=current_user.id,
        name=payload.name,
        slug=slug,
        description=payload.description,
        space_type=payload.space_type,
        visibility=payload.visibility,
        default_classification=payload.default_classification,
        publish_policy=payload.publish_policy,
        review_cycle_days=payload.review_cycle_days,
        space_metadata=payload.metadata,
    )
    db.add(row)
    await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action="knowledge_space.create",
        resource_type="knowledge_space",
        resource_id=row.id,
        payload={"space_type": row.space_type, "visibility": row.visibility},
    )
    return {"id": row.id, "slug": row.slug, "role": "admin"}


@router.patch("/knowledge/spaces/{space_id}")
async def update_space(
    space_id: str,
    payload: KnowledgeSpaceUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    space, _, _ = await _space_or_error(
        db, request=request, user=current_user, space_id=space_id, role="admin"
    )
    if not current_user.is_superuser and payload.visibility == "tenant":
        raise AppException(
            ErrorCodes.PERMISSION_DENIED.code,
            message="Tenant-visible knowledge spaces require admin permission",
        )
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(space, field, value)
    await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action="knowledge_space.update",
        resource_type="knowledge_space",
        resource_id=space.id,
        payload={"fields": sorted(payload.model_dump(exclude_none=True))},
    )
    return {"updated": True, "id": space.id}


@router.get("/knowledge/spaces/{space_id}/members")
async def list_space_members(
    space_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, tenant_id, workspace_id = await _space_or_error(
        db, request=request, user=current_user, space_id=space_id, role="admin"
    )
    rows = list(
        (
            await db.execute(
                select(KnowledgeSpaceMember).where(
                    KnowledgeSpaceMember.space_id == space_id,
                    KnowledgeSpaceMember.tenant_id == tenant_id,
                    KnowledgeSpaceMember.workspace_id == workspace_id,
                )
            )
        ).scalars()
    )
    return {
        "items": [
            {
                "id": row.id,
                "subject_type": row.subject_type,
                "subject_id": row.subject_id,
                "role": row.role,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            }
            for row in rows
        ]
    }


@router.post("/knowledge/spaces/{space_id}/members")
async def grant_space_member(
    space_id: str,
    payload: SpaceMemberGrant,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, tenant_id, workspace_id = await _space_or_error(
        db, request=request, user=current_user, space_id=space_id, role="admin"
    )
    if payload.subject_type == "user":
        subject = await db.get(User, payload.subject_id)
        if subject is None or subject.status != "active":
            raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Active user not found")
    row = await db.scalar(
        select(KnowledgeSpaceMember).where(
            KnowledgeSpaceMember.space_id == space_id,
            KnowledgeSpaceMember.subject_type == payload.subject_type,
            KnowledgeSpaceMember.subject_id == payload.subject_id,
        )
    )
    if row is None:
        row = KnowledgeSpaceMember(
            id=str(uuid.uuid4()),
            space_id=space_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            subject_type=payload.subject_type,
            subject_id=payload.subject_id,
            granted_by=current_user.id,
        )
        db.add(row)
    row.role = payload.role
    row.expires_at = payload.expires_at
    row.granted_by = current_user.id
    await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action="knowledge_space.member.grant",
        resource_type="knowledge_space",
        resource_id=space_id,
        payload={"subject_type": row.subject_type, "subject_id": row.subject_id, "role": row.role},
    )
    return {"id": row.id, "role": row.role}


@router.delete("/knowledge/spaces/{space_id}/members/{member_id}")
async def revoke_space_member(
    space_id: str,
    member_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, tenant_id, workspace_id = await _space_or_error(
        db, request=request, user=current_user, space_id=space_id, role="admin"
    )
    row = await db.scalar(
        select(KnowledgeSpaceMember).where(
            KnowledgeSpaceMember.id == member_id,
            KnowledgeSpaceMember.space_id == space_id,
            KnowledgeSpaceMember.tenant_id == tenant_id,
            KnowledgeSpaceMember.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Space member not found")
    subject_type, subject_id = row.subject_type, row.subject_id
    await db.delete(row)
    await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action="knowledge_space.member.revoke",
        resource_type="knowledge_space",
        resource_id=space_id,
        payload={"subject_type": subject_type, "subject_id": subject_id},
    )
    return {"revoked": True, "id": member_id}


@router.post("/knowledge/principal-memberships")
async def upsert_principal_membership(
    payload: PrincipalMembershipUpsert,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not current_user.is_superuser:
        raise AppException(ErrorCodes.PERMISSION_DENIED.code, message="Admin permission required")
    tenant_id, workspace_id = _scope(request, current_user)
    subject = await db.get(User, payload.user_id)
    if subject is None or subject.status != "active":
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Active user not found")
    row = await db.scalar(
        select(KnowledgePrincipalMembership).where(
            KnowledgePrincipalMembership.tenant_id == tenant_id,
            KnowledgePrincipalMembership.workspace_id == workspace_id,
            KnowledgePrincipalMembership.user_id == payload.user_id,
            KnowledgePrincipalMembership.principal_type == payload.principal_type,
            KnowledgePrincipalMembership.principal_id == payload.principal_id,
        )
    )
    if row is None:
        row = KnowledgePrincipalMembership(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            user_id=payload.user_id,
            principal_type=payload.principal_type,
            principal_id=payload.principal_id,
        )
        db.add(row)
    row.source = payload.source
    row.status = "active"
    row.effective_from = payload.effective_from
    row.effective_to = payload.effective_to
    row.membership_metadata = payload.metadata
    await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action="knowledge_principal.upsert",
        resource_type="user",
        resource_id=payload.user_id,
        payload={
            "principal_type": payload.principal_type,
            "principal_id": payload.principal_id,
            "source": payload.source,
        },
    )
    return {"id": row.id, "status": row.status}


@router.post("/knowledge/spaces/{space_id}/projects/{project_id}")
async def attach_space_project(
    space_id: str,
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, tenant_id, workspace_id = await _space_or_error(
        db, request=request, user=current_user, space_id=space_id, role="admin"
    )
    project = await db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == current_user.id,
            Project.tenant_id == tenant_id,
            Project.workspace_id == workspace_id,
        )
    )
    if project is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Project not found")
    row = await db.scalar(
        select(KnowledgeSpaceProject).where(
            KnowledgeSpaceProject.space_id == space_id,
            KnowledgeSpaceProject.project_id == project_id,
        )
    )
    if row is None:
        row = KnowledgeSpaceProject(
            id=str(uuid.uuid4()),
            space_id=space_id,
            project_id=project_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            attached_by=current_user.id,
        )
        db.add(row)
        await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action="knowledge_space.project.attach",
        resource_type="knowledge_space",
        resource_id=space_id,
        payload={"project_id": project_id},
    )
    return {"attached": True, "space_id": space_id, "project_id": project_id}


@router.get("/knowledge/connectors")
async def list_connectors(
    request: Request,
    space_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = _scope(request, current_user)
    context = await resolve_access_context(
        db, user=current_user, tenant_id=tenant_id, workspace_id=workspace_id
    )
    admin_space_ids = [
        item for item, role in context.space_roles.items() if role_allows(role, "admin")
    ]
    stmt = select(KnowledgeConnector).where(
        KnowledgeConnector.tenant_id == tenant_id,
        KnowledgeConnector.workspace_id == workspace_id,
        KnowledgeConnector.space_id.in_(admin_space_ids) if admin_space_ids else False,
    )
    if space_id:
        stmt = stmt.where(KnowledgeConnector.space_id == space_id)
    rows = list((await db.execute(stmt.order_by(KnowledgeConnector.name))).scalars())
    return {
        "items": [
            {
                "id": row.id,
                "space_id": row.space_id,
                "name": row.name,
                "connector_type": row.connector_type,
                "status": row.status,
                "sync_cursor": row.sync_cursor,
                "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
                "last_error": row.last_error,
            }
            for row in rows
        ]
    }


@router.post("/knowledge/connectors")
async def create_connector(
    payload: ConnectorCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, tenant_id, workspace_id = await _space_or_error(
        db, request=request, user=current_user, space_id=payload.space_id, role="admin"
    )
    row = KnowledgeConnector(
        id=str(uuid.uuid4()),
        space_id=payload.space_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        owner_id=current_user.id,
        name=payload.name,
        connector_type=payload.connector_type,
        base_url=str(payload.base_url) if payload.base_url else None,
        credential_ref=payload.credential_ref,
        sync_interval_seconds=payload.sync_interval_seconds,
        connector_config=payload.config,
    )
    db.add(row)
    await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action="knowledge_connector.create",
        resource_type="knowledge_connector",
        resource_id=row.id,
        payload={"space_id": row.space_id, "connector_type": row.connector_type},
    )
    return {"id": row.id, "status": row.status}


@router.post("/knowledge/connectors/{connector_id}/push", status_code=202)
async def push_connector_snapshots(
    connector_id: str,
    payload: ConnectorPushRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """持久化增量 Snapshot；实际摄入、ACL 和编译仅由 Worker 执行。"""
    tenant_id, workspace_id = _scope(request, current_user)
    connector = await db.scalar(
        select(KnowledgeConnector).where(
            KnowledgeConnector.id == connector_id,
            KnowledgeConnector.tenant_id == tenant_id,
            KnowledgeConnector.workspace_id == workspace_id,
        )
    )
    if connector is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Connector not found")
    await _space_or_error(
        db, request=request, user=current_user, space_id=connector.space_id, role="admin"
    )
    batch_material = "\n".join(
        [
            str(payload.cursor or ""),
            *(
                f"{item.external_id}:{content_hash(item.content)}:{int(item.deleted)}"
                for item in payload.snapshots
            ),
        ]
    )
    batch_hash = hashlib.sha256(batch_material.encode("utf-8")).hexdigest()
    recent_runs = list(
        (
            await db.execute(
                select(KnowledgeSyncRun)
                .where(KnowledgeSyncRun.connector_id == connector.id)
                .order_by(KnowledgeSyncRun.started_at.desc())
                .limit(20)
            )
        ).scalars()
    )
    duplicate = next(
        (
            row
            for row in recent_runs
            if (row.stats or {}).get("batch_hash") == batch_hash
            and row.status in {"pending", "running", "succeeded"}
        ),
        None,
    )
    if duplicate is not None:
        return {
            "accepted": True,
            "deduplicated": True,
            "run_id": duplicate.id,
            "status": duplicate.status,
            "queued": int((duplicate.stats or {}).get("queued", 0)),
        }

    run = KnowledgeSyncRun(
        id=str(uuid.uuid4()),
        connector_id=connector.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        status="pending",
        cursor_before=connector.sync_cursor,
        cursor_after=payload.cursor,
        stats={"batch_hash": batch_hash, "queued": len(payload.snapshots)},
    )
    db.add(run)
    await db.flush()
    for snapshot in payload.snapshots:
        db.add(
            KnowledgeSyncItem(
                id=str(uuid.uuid4()),
                run_id=run.id,
                connector_id=connector.id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                external_id=snapshot.external_id,
                title=snapshot.title,
                content=snapshot.content,
                content_type=snapshot.content_type,
                content_hash=content_hash(snapshot.content),
                deleted=snapshot.deleted,
                authority=snapshot.authority,
                classification=snapshot.classification,
                effective_from=snapshot.effective_from,
                effective_to=snapshot.effective_to,
                source_metadata=snapshot.metadata,
                acl_snapshot=[item.model_dump(mode="json") for item in snapshot.acl],
                status="pending",
            )
        )
    await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action="knowledge_connector.sync.queued",
        resource_type="knowledge_connector",
        resource_id=connector.id,
        payload={"run_id": run.id, "queued": len(payload.snapshots)},
    )
    return {
        "accepted": True,
        "deduplicated": False,
        "run_id": run.id,
        "status": run.status,
        "queued": len(payload.snapshots),
    }


@router.get("/knowledge/sync-runs")
async def list_sync_runs(
    request: Request,
    connector_id: str | None = None,
    space_id: str | None = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = _scope(request, current_user)
    context = await resolve_access_context(
        db, user=current_user, tenant_id=tenant_id, workspace_id=workspace_id
    )
    admin_space_ids = [
        item for item, role in context.space_roles.items() if role_allows(role, "admin")
    ]
    stmt = (
        select(KnowledgeSyncRun, KnowledgeConnector)
        .join(KnowledgeConnector, KnowledgeSyncRun.connector_id == KnowledgeConnector.id)
        .where(
            KnowledgeSyncRun.tenant_id == tenant_id,
            KnowledgeSyncRun.workspace_id == workspace_id,
            KnowledgeConnector.space_id.in_(admin_space_ids) if admin_space_ids else False,
        )
    )
    if connector_id:
        stmt = stmt.where(KnowledgeSyncRun.connector_id == connector_id)
    if space_id:
        stmt = stmt.where(KnowledgeConnector.space_id == space_id)
    rows = (
        await db.execute(
            stmt.order_by(KnowledgeSyncRun.started_at.desc()).limit(max(1, min(limit, 200)))
        )
    ).all()
    return {
        "items": [
            {
                "id": run.id,
                "connector_id": run.connector_id,
                "connector_name": connector.name,
                "status": run.status,
                "cursor_before": run.cursor_before,
                "cursor_after": run.cursor_after,
                "stats": run.stats,
                "error": run.error,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            }
            for run, connector in rows
        ]
    }


@router.get("/knowledge/sync-runs/{run_id}/items")
async def list_sync_run_items(
    run_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = _scope(request, current_user)
    run = await db.scalar(
        select(KnowledgeSyncRun).where(
            KnowledgeSyncRun.id == run_id,
            KnowledgeSyncRun.tenant_id == tenant_id,
            KnowledgeSyncRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Sync run not found")
    connector = await db.get(KnowledgeConnector, run.connector_id)
    if connector is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Connector not found")
    await _space_or_error(
        db, request=request, user=current_user, space_id=connector.space_id, role="admin"
    )
    rows = list(
        (
            await db.execute(
                select(KnowledgeSyncItem)
                .where(KnowledgeSyncItem.run_id == run_id)
                .order_by(KnowledgeSyncItem.created_at)
            )
        ).scalars()
    )
    return {
        "items": [
            {
                "id": item.id,
                "external_id": item.external_id,
                "title": item.title,
                "deleted": item.deleted,
                "status": item.status,
                "attempts": item.attempts,
                "document_id": item.document_id,
                "source_id": item.source_id,
                "error": item.error,
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            }
            for item in rows
        ]
    }


@router.post("/knowledge/sync-runs/{run_id}/retry")
async def retry_knowledge_sync_run(
    run_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = _scope(request, current_user)
    run = await db.scalar(
        select(KnowledgeSyncRun).where(
            KnowledgeSyncRun.id == run_id,
            KnowledgeSyncRun.tenant_id == tenant_id,
            KnowledgeSyncRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Sync run not found")
    connector = await db.get(KnowledgeConnector, run.connector_id)
    if connector is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Connector not found")
    await _space_or_error(
        db, request=request, user=current_user, space_id=connector.space_id, role="admin"
    )
    try:
        result = await retry_sync_run(run_id)
    except ValueError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc)) from exc
    await write_audit_log(
        user_id=current_user.id,
        action="knowledge_connector.sync.retry",
        resource_type="knowledge_connector",
        resource_id=connector.id,
        payload={"run_id": run_id, "requeued": result["requeued"]},
    )
    return result


@router.post("/knowledge/reviews/reconcile-due")
async def reconcile_due_reviews(
    request: Request,
    space_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reviewer 手动扫描到期复审；Worker 也会周期执行同一逻辑。"""
    tenant_id, workspace_id = _scope(request, current_user)
    context = await resolve_access_context(
        db, user=current_user, tenant_id=tenant_id, workspace_id=workspace_id
    )
    review_space_ids = tuple(
        item for item, role in context.space_roles.items() if role_allows(role, "reviewer")
    )
    if space_id:
        if space_id not in review_space_ids:
            raise AppException(
                ErrorCodes.PERMISSION_DENIED.code, message="knowledge_space_requires_reviewer"
            )
        review_space_ids = (space_id,)
    result = await reopen_due_review_tasks(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        space_ids=review_space_ids,
    )
    await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action="knowledge_review.reconcile_due",
        resource_type="knowledge_space",
        resource_id=space_id or workspace_id,
        payload=result,
    )
    return result


@router.get("/knowledge/reviews")
async def list_reviews(
    request: Request,
    status: str = "pending",
    space_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = _scope(request, current_user)
    context = await resolve_access_context(
        db, user=current_user, tenant_id=tenant_id, workspace_id=workspace_id
    )
    review_space_ids = [
        item for item, role in context.space_roles.items() if role_allows(role, "reviewer")
    ]
    if space_id:
        if space_id not in review_space_ids:
            raise AppException(
                ErrorCodes.PERMISSION_DENIED.code, message="knowledge_space_requires_reviewer"
            )
        review_space_ids = [space_id]
    source_access = accessible_source_predicate(context)
    rows = list(
        (
            await db.execute(
                select(KnowledgeReviewTask, KnowledgeSourceVersion, KnowledgeSource)
                .join(
                    KnowledgeSourceVersion,
                    KnowledgeReviewTask.source_version_id == KnowledgeSourceVersion.id,
                )
                .join(KnowledgeSource, KnowledgeSourceVersion.source_id == KnowledgeSource.id)
                .where(
                    KnowledgeReviewTask.tenant_id == tenant_id,
                    KnowledgeReviewTask.workspace_id == workspace_id,
                    KnowledgeReviewTask.status == status,
                    (
                        KnowledgeReviewTask.space_id.in_(review_space_ids)
                        if review_space_ids
                        else False
                    ),
                    source_access,
                )
                .order_by(KnowledgeReviewTask.created_at)
            )
        ).all()
    )
    return {
        "items": [
            {
                "id": task.id,
                "source_id": source.id,
                "source_title": source.title,
                "source_version_id": task.source_version_id,
                "version_number": version.version_number,
                "space_id": task.space_id,
                "status": task.status,
                "required_role": task.required_role,
                "requested_by": task.requested_by,
                "assigned_to": task.assigned_to,
                "review_reason": (task.diff_summary or {}).get("review_reason", "content_change"),
                "review_due_at": source.review_due_at.isoformat() if source.review_due_at else None,
                "classification": source.classification,
                "authority": source.authority,
                "source_system": source.source_system,
                "diff_summary": task.diff_summary,
                "created_at": task.created_at.isoformat() if task.created_at else None,
            }
            for task, version, source in rows
        ]
    }


@router.post("/knowledge/reviews/{review_id}/decision")
async def decide_review(
    review_id: str,
    payload: ReviewDecision,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = _scope(request, current_user)
    task = await db.scalar(
        select(KnowledgeReviewTask).where(
            KnowledgeReviewTask.id == review_id,
            KnowledgeReviewTask.tenant_id == tenant_id,
            KnowledgeReviewTask.workspace_id == workspace_id,
        )
    )
    if task is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Review task not found")
    if task.space_id:
        await _space_or_error(
            db, request=request, user=current_user, space_id=task.space_id, role="publisher"
        )
    context = await resolve_access_context(
        db, user=current_user, tenant_id=tenant_id, workspace_id=workspace_id
    )
    source = await db.scalar(
        select(KnowledgeSource)
        .join(KnowledgeSourceVersion, KnowledgeSourceVersion.source_id == KnowledgeSource.id)
        .where(
            KnowledgeSourceVersion.id == task.source_version_id,
            accessible_source_predicate(context),
        )
    )
    if source is None or not classification_allows(context.clearance, source.classification):
        raise AppException(
            ErrorCodes.PERMISSION_DENIED.code, message="Knowledge review source access denied"
        )
    try:
        if payload.decision == "approve":
            result = await publish_source_version(
                db,
                source_version_id=task.source_version_id,
                decided_by=current_user.id,
                comment=payload.comment or None,
            )
        else:
            if not payload.comment.strip():
                raise AppException(
                    ErrorCodes.PARAM_INVALID.code, message="Reject comment is required"
                )
            result = await reject_source_version(
                db,
                source_version_id=task.source_version_id,
                decided_by=current_user.id,
                comment=payload.comment,
            )
    except ValueError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc)) from exc
    await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action=f"knowledge_review.{payload.decision}",
        resource_type="knowledge_review",
        resource_id=task.id,
        payload={"source_version_id": task.source_version_id},
    )
    return result


@router.post("/knowledge/sources/{source_id}/withdraw")
async def withdraw_knowledge_source(
    source_id: str,
    payload: WithdrawRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = _scope(request, current_user)
    source = await db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.tenant_id == tenant_id,
            KnowledgeSource.workspace_id == workspace_id,
        )
    )
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Knowledge source not found")
    if source.space_id:
        await _space_or_error(
            db, request=request, user=current_user, space_id=source.space_id, role="publisher"
        )
    elif source.owner_id != current_user.id:
        raise AppException(ErrorCodes.PERMISSION_DENIED.code, message="Source permission denied")
    result = await withdraw_source(
        db, source=source, decided_by=current_user.id, reason=payload.reason
    )
    await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action="knowledge_source.withdraw",
        resource_type="knowledge_source",
        resource_id=source.id,
        payload={"reason": payload.reason},
    )
    return result
