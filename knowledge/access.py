"""企业知识空间授权与来源可见性单一入口。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, exists, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    KnowledgePrincipalMembership,
    KnowledgeSource,
    KnowledgeSourcePermission,
    KnowledgeSpace,
    KnowledgeSpaceMember,
    KnowledgeSpaceProject,
    Project,
    User,
)

SPACE_ROLE_RANK = {"viewer": 1, "contributor": 2, "reviewer": 3, "publisher": 4, "admin": 5}
CLASSIFICATION_RANK = {"public": 1, "internal": 2, "confidential": 3, "restricted": 4}


@dataclass(frozen=True, slots=True)
class KnowledgeAccessContext:
    user_id: str
    tenant_id: str
    workspace_id: str
    subjects: tuple[tuple[str, str], ...]
    clearance: str
    space_roles: dict[str, str]

    @property
    def accessible_space_ids(self) -> tuple[str, ...]:
        return tuple(self.space_roles)


def role_allows(actual: str | None, required: str) -> bool:
    return SPACE_ROLE_RANK.get(actual or "", 0) >= SPACE_ROLE_RANK.get(required, 99)


def classification_allows(clearance: str, classification: str | None) -> bool:
    return CLASSIFICATION_RANK.get(classification or "internal", 2) <= CLASSIFICATION_RANK.get(
        clearance, 2
    )


async def resolve_access_context(
    db: AsyncSession,
    *,
    user: User,
    tenant_id: str,
    workspace_id: str,
    project_id: str | None = None,
) -> KnowledgeAccessContext:
    """解析用户、组织主体、空间角色和密级上限。"""

    now = datetime.now(UTC)
    subjects: set[tuple[str, str]] = {("user", user.id)}
    memberships = list(
        (
            await db.execute(
                select(KnowledgePrincipalMembership).where(
                    KnowledgePrincipalMembership.user_id == user.id,
                    KnowledgePrincipalMembership.tenant_id == tenant_id,
                    KnowledgePrincipalMembership.workspace_id == workspace_id,
                    KnowledgePrincipalMembership.status == "active",
                    or_(
                        KnowledgePrincipalMembership.effective_from.is_(None),
                        KnowledgePrincipalMembership.effective_from <= now,
                    ),
                    or_(
                        KnowledgePrincipalMembership.effective_to.is_(None),
                        KnowledgePrincipalMembership.effective_to > now,
                    ),
                )
            )
        ).scalars()
    )
    clearance = "restricted" if user.is_superuser else "internal"
    for membership in memberships:
        if membership.principal_type == "clearance":
            if CLASSIFICATION_RANK.get(membership.principal_id, 0) > CLASSIFICATION_RANK.get(
                clearance, 0
            ):
                clearance = membership.principal_id
            continue
        subjects.add((membership.principal_type, membership.principal_id))

    if project_id:
        project = await db.scalar(
            select(Project).where(
                Project.id == project_id,
                Project.tenant_id == tenant_id,
                Project.workspace_id == workspace_id,
                Project.user_id == user.id,
            )
        )
        if project is not None:
            subjects.add(("project", project.id))

    member_filters = [
        and_(
            KnowledgeSpaceMember.subject_type == subject_type,
            KnowledgeSpaceMember.subject_id == subject_id,
        )
        for subject_type, subject_id in sorted(subjects)
    ]
    stmt = (
        select(KnowledgeSpace, KnowledgeSpaceMember.role)
        .outerjoin(
            KnowledgeSpaceMember,
            and_(
                KnowledgeSpaceMember.space_id == KnowledgeSpace.id,
                or_(*member_filters) if member_filters else false(),
                or_(
                    KnowledgeSpaceMember.expires_at.is_(None),
                    KnowledgeSpaceMember.expires_at > now,
                ),
            ),
        )
        .where(
            KnowledgeSpace.tenant_id == tenant_id,
            KnowledgeSpace.workspace_id == workspace_id,
            KnowledgeSpace.status == "active",
            or_(
                KnowledgeSpace.owner_id == user.id,
                KnowledgeSpace.visibility == "tenant",
                KnowledgeSpaceMember.id.is_not(None),
            ),
        )
    )
    if project_id:
        mounted = exists(
            select(KnowledgeSpaceProject.id).where(
                KnowledgeSpaceProject.space_id == KnowledgeSpace.id,
                KnowledgeSpaceProject.project_id == project_id,
            )
        )
        stmt = stmt.where(or_(KnowledgeSpace.space_type != "project", mounted))

    roles: dict[str, str] = {}
    for space, member_role in (await db.execute(stmt)).all():
        role = "admin" if space.owner_id == user.id else (member_role or "viewer")
        previous = roles.get(space.id)
        if previous is None or SPACE_ROLE_RANK[role] > SPACE_ROLE_RANK[previous]:
            roles[space.id] = role
    return KnowledgeAccessContext(
        user_id=user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        subjects=tuple(sorted(subjects)),
        clearance=clearance,
        space_roles=roles,
    )


async def require_space_role(
    db: AsyncSession,
    *,
    user: User,
    tenant_id: str,
    workspace_id: str,
    space_id: str,
    required_role: str,
) -> tuple[KnowledgeSpace, str]:
    context = await resolve_access_context(
        db,
        user=user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    role = context.space_roles.get(space_id)
    space = await db.scalar(
        select(KnowledgeSpace).where(
            KnowledgeSpace.id == space_id,
            KnowledgeSpace.tenant_id == tenant_id,
            KnowledgeSpace.workspace_id == workspace_id,
        )
    )
    if space is None or not role_allows(role, required_role):
        raise PermissionError(f"knowledge_space_requires_{required_role}")
    return space, role or "viewer"


def accessible_source_predicate(
    context: KnowledgeAccessContext,
    *,
    project_id: str | None = None,
):
    """构造查询时 ACL 条件；旧 owner 资产继续兼容。"""

    now = datetime.now(UTC)
    subject_filters = [
        and_(
            KnowledgeSourcePermission.subject_type == subject_type,
            KnowledgeSourcePermission.subject_id == subject_id,
        )
        for subject_type, subject_id in context.subjects
    ]
    has_source_acl = exists(
        select(KnowledgeSourcePermission.id).where(
            KnowledgeSourcePermission.source_id == KnowledgeSource.id,
            or_(
                KnowledgeSourcePermission.expires_at.is_(None),
                KnowledgeSourcePermission.expires_at > now,
            ),
        )
    )
    matches_source_acl = exists(
        select(KnowledgeSourcePermission.id).where(
            KnowledgeSourcePermission.source_id == KnowledgeSource.id,
            or_(*subject_filters) if subject_filters else false(),
            KnowledgeSourcePermission.permission.in_(("view", "edit", "admin")),
            or_(
                KnowledgeSourcePermission.expires_at.is_(None),
                KnowledgeSourcePermission.expires_at > now,
            ),
        )
    )
    scope_access = or_(
        KnowledgeSource.owner_id == context.user_id,
        and_(
            (
                KnowledgeSource.space_id.in_(context.accessible_space_ids)
                if context.accessible_space_ids
                else false()
            ),
            or_(~has_source_acl, matches_source_acl),
        ),
    )
    validity = and_(
        KnowledgeSource.deleted_at.is_(None),
        or_(KnowledgeSource.effective_from.is_(None), KnowledgeSource.effective_from <= now),
        or_(KnowledgeSource.effective_to.is_(None), KnowledgeSource.effective_to > now),
    )
    classification_filters = [
        KnowledgeSource.classification == level
        for level, rank in CLASSIFICATION_RANK.items()
        if rank <= CLASSIFICATION_RANK.get(context.clearance, 2)
    ]
    project_scope = True
    if project_id:
        mounted = exists(
            select(KnowledgeSpaceProject.id).where(
                KnowledgeSpaceProject.space_id == KnowledgeSource.space_id,
                KnowledgeSpaceProject.project_id == project_id,
            )
        )
        enterprise_space = exists(
            select(KnowledgeSpace.id).where(
                KnowledgeSpace.id == KnowledgeSource.space_id,
                KnowledgeSpace.space_type.in_(("company", "department", "role", "personal")),
            )
        )
        project_scope = or_(
            KnowledgeSource.project_id == project_id,
            mounted,
            enterprise_space,
        )
    return and_(scope_access, validity, or_(*classification_filters), project_scope)
