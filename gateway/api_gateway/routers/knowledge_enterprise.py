"""企业知识库空间、权限和发布治理 API。"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.audit.logger import write_audit_log
from infra.errors import AppException, ErrorCodes
from infra.security.identity import is_enterprise_admin
from infra.security.resource_scope import normalized_tenant_scope
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    KnowledgePage,
    KnowledgePrincipalMembership,
    KnowledgeReviewTask,
    KnowledgeSource,
    KnowledgeSourceVersion,
    KnowledgeSpace,
    KnowledgeSpaceMember,
    User,
)
from knowledge.access import (
    accessible_source_predicate,
    classification_allows,
    require_space_role,
    resolve_access_context,
    role_allows,
)
from knowledge.lifecycle import (
    publish_source_version,
    reject_source_version,
    reopen_due_review_tasks,
    withdraw_source,
)
from knowledge.query import search_knowledge

router = APIRouter()

SpaceType = Literal["company", "department", "role", "workspace", "personal"]
SpaceRole = Literal["viewer", "contributor", "reviewer", "publisher", "admin"]
Classification = Literal["public", "internal", "confidential", "restricted"]
SubjectType = Literal["user", "department", "group", "role"]


class KnowledgeSpaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=128)
    description: str = Field(default="", max_length=4000)
    space_type: SpaceType = "workspace"
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


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
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
    if not is_enterprise_admin(current_user) and (
        payload.space_type != "personal" or payload.visibility == "tenant"
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
    if not is_enterprise_admin(current_user) and payload.visibility == "tenant":
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
    if not is_enterprise_admin(current_user):
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
