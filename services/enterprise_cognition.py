"""企业认知实体、发布治理与 Responses 上下文投影。"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    AuditLog,
    EnterpriseCognitiveEntity,
    EnterpriseCognitiveVersion,
    EnterpriseDirectoryMembership,
    EnterpriseDirectoryPrincipal,
    KnowledgeSpace,
    User,
)
from knowledge.access import classification_allows, resolve_access_context

ENTITY_TYPES = {"company", "department"}
VERSION_STATUSES = {"draft", "published", "archived"}
CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}
ENTERPRISE_GROUNDING_PATTERN = re.compile(
    r"公司|本公司|部门|本部门|我们|组织|制度|流程|规范|政策|审批|职责|负责人|"
    r"战略|使命|愿景|价值观|产品|服务|业务|口径|SOP|sop",
    re.IGNORECASE,
)


@dataclass(slots=True)
class EnterpriseContextBundle:
    prompt: str = ""
    entities: list[dict[str, Any]] = field(default_factory=list)
    knowledge_space_ids: list[str] = field(default_factory=list)
    requires_grounding: bool = False

    def manifest(self) -> dict[str, Any]:
        return {
            "entity_count": len(self.entities),
            "entities": [
                {
                    "entity_id": item["entity_id"],
                    "entity_type": item["entity_type"],
                    "entity_key": item["entity_key"],
                    "version_id": item["version_id"],
                    "version": item["version"],
                    "classification": item["classification"],
                    "knowledge_space_id": item.get("knowledge_space_id"),
                }
                for item in self.entities
            ],
            "knowledge_space_ids": list(self.knowledge_space_ids),
            "requires_grounding": self.requires_grounding,
        }


def cognitive_entity_payload(
    row: EnterpriseCognitiveEntity,
    *,
    principal: EnterpriseDirectoryPrincipal | None = None,
    space: KnowledgeSpace | None = None,
    current_version: EnterpriseCognitiveVersion | None = None,
    draft_version: EnterpriseCognitiveVersion | None = None,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "entity_type": row.entity_type,
        "entity_key": row.entity_key,
        "display_name": row.display_name,
        "directory_principal_id": row.directory_principal_id,
        "department_external_id": principal.external_id if principal else None,
        "department_name": principal.display_name if principal else None,
        "knowledge_space_id": row.knowledge_space_id,
        "knowledge_space_name": space.name if space else None,
        "status": row.status,
        "current_version": cognitive_version_payload(current_version),
        "draft_version": cognitive_version_payload(draft_version),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def cognitive_version_payload(row: EnterpriseCognitiveVersion | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "entity_id": row.entity_id,
        "version": row.version,
        "status": row.status,
        "classification": row.classification,
        "summary": row.summary,
        "mission": row.mission,
        "vision": row.vision,
        "values": list(row.values or []),
        "responsibilities": list(row.responsibilities or []),
        "products_services": list(row.products_services or []),
        "operating_principles": list(row.operating_principles or []),
        "terminology": dict(row.terminology or {}),
        "key_contacts": list(row.key_contacts or []),
        "source_refs": list(row.source_refs or []),
        "metadata": dict(row.context_metadata or {}),
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "review_due_at": row.review_due_at.isoformat() if row.review_due_at else None,
        "published_by": row.published_by,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def list_cognitive_entities(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    org_id: str | None = None,
) -> list[dict[str, Any]]:
    scope_filters = [
        EnterpriseCognitiveEntity.tenant_id == tenant_id,
        EnterpriseCognitiveEntity.workspace_id == workspace_id,
    ]
    if org_id:
        scope_filters.append(
            or_(
                EnterpriseCognitiveEntity.entity_type == "department",
                and_(
                    EnterpriseCognitiveEntity.entity_type == "company",
                    EnterpriseCognitiveEntity.entity_key == org_id,
                ),
            )
        )
    entities = list(
        (
            await db.execute(
                select(EnterpriseCognitiveEntity)
                .where(*scope_filters)
                .order_by(
                    EnterpriseCognitiveEntity.entity_type,
                    EnterpriseCognitiveEntity.display_name,
                )
            )
        ).scalars()
    )
    if not entities:
        return []
    principal_ids = {row.directory_principal_id for row in entities if row.directory_principal_id}
    space_ids = {row.knowledge_space_id for row in entities if row.knowledge_space_id}
    principals = {
        row.id: row
        for row in (
            list(
                (
                    await db.execute(
                        select(EnterpriseDirectoryPrincipal).where(
                            EnterpriseDirectoryPrincipal.id.in_(principal_ids)
                        )
                    )
                ).scalars()
            )
            if principal_ids
            else []
        )
    }
    spaces = {
        row.id: row
        for row in (
            list(
                (
                    await db.execute(select(KnowledgeSpace).where(KnowledgeSpace.id.in_(space_ids)))
                ).scalars()
            )
            if space_ids
            else []
        )
    }
    versions = list(
        (
            await db.execute(
                select(EnterpriseCognitiveVersion)
                .where(EnterpriseCognitiveVersion.entity_id.in_([row.id for row in entities]))
                .order_by(
                    EnterpriseCognitiveVersion.entity_id,
                    EnterpriseCognitiveVersion.version.desc(),
                )
            )
        ).scalars()
    )
    current: dict[str, EnterpriseCognitiveVersion] = {}
    drafts: dict[str, EnterpriseCognitiveVersion] = {}
    for version in versions:
        if version.status == "published" and version.entity_id not in current:
            current[version.entity_id] = version
        elif version.status == "draft" and version.entity_id not in drafts:
            drafts[version.entity_id] = version
    return [
        cognitive_entity_payload(
            row,
            principal=principals.get(row.directory_principal_id or ""),
            space=spaces.get(row.knowledge_space_id or ""),
            current_version=current.get(row.id),
            draft_version=drafts.get(row.id),
        )
        for row in entities
    ]


async def list_cognitive_versions(
    db: AsyncSession,
    *,
    entity_id: str,
    tenant_id: str,
    workspace_id: str,
) -> list[dict[str, Any]]:
    rows = list(
        (
            await db.execute(
                select(EnterpriseCognitiveVersion)
                .where(
                    EnterpriseCognitiveVersion.entity_id == entity_id,
                    EnterpriseCognitiveVersion.tenant_id == tenant_id,
                    EnterpriseCognitiveVersion.workspace_id == workspace_id,
                )
                .order_by(EnterpriseCognitiveVersion.version.desc())
            )
        ).scalars()
    )
    return [cognitive_version_payload(row) or {} for row in rows]


async def create_cognitive_entity(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    org_id: str,
    actor: User,
    entity_type: str,
    display_name: str,
    department_external_id: str | None,
    knowledge_space_id: str | None,
) -> EnterpriseCognitiveEntity:
    if entity_type not in ENTITY_TYPES:
        raise ValueError("unsupported_cognitive_entity_type")
    principal: EnterpriseDirectoryPrincipal | None = None
    entity_key = org_id
    if entity_type == "department":
        if not department_external_id:
            raise ValueError("department_external_id_required")
        principal = await db.scalar(
            select(EnterpriseDirectoryPrincipal).where(
                EnterpriseDirectoryPrincipal.tenant_id == tenant_id,
                EnterpriseDirectoryPrincipal.workspace_id == workspace_id,
                EnterpriseDirectoryPrincipal.principal_type == "department",
                EnterpriseDirectoryPrincipal.external_id == department_external_id,
                EnterpriseDirectoryPrincipal.status == "active",
            )
        )
        if principal is None:
            raise ValueError("department_principal_not_found")
        entity_key = principal.external_id
        display_name = display_name.strip() or principal.display_name
    space = await _validate_cognitive_space(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        space_id=knowledge_space_id,
        entity_type=entity_type,
    )
    existing = await db.scalar(
        select(EnterpriseCognitiveEntity).where(
            EnterpriseCognitiveEntity.tenant_id == tenant_id,
            EnterpriseCognitiveEntity.workspace_id == workspace_id,
            EnterpriseCognitiveEntity.entity_type == entity_type,
            EnterpriseCognitiveEntity.entity_key == entity_key,
        )
    )
    if existing is not None:
        existing.display_name = display_name.strip() or existing.display_name
        existing.directory_principal_id = principal.id if principal else None
        existing.knowledge_space_id = space.id if space else None
        existing.status = "active"
        entity = existing
    else:
        entity = EnterpriseCognitiveEntity(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            entity_type=entity_type,
            entity_key=entity_key,
            display_name=display_name.strip(),
            directory_principal_id=principal.id if principal else None,
            knowledge_space_id=space.id if space else None,
            status="active",
            created_by=actor.id,
        )
        db.add(entity)
    await db.flush()
    _add_audit(
        db,
        actor=actor,
        action="enterprise_cognitive_entity_upsert",
        resource_id=entity.id,
        payload={
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "entity_type": entity_type,
            "entity_key": entity_key,
            "knowledge_space_id": knowledge_space_id,
        },
    )
    return entity


async def save_cognitive_draft(
    db: AsyncSession,
    *,
    entity: EnterpriseCognitiveEntity,
    actor: User,
    values: dict[str, Any],
) -> EnterpriseCognitiveVersion:
    locked = await db.scalar(
        select(EnterpriseCognitiveEntity)
        .where(EnterpriseCognitiveEntity.id == entity.id)
        .with_for_update()
    )
    if locked is None:
        raise ValueError("cognitive_entity_not_found")
    if locked.status != "active":
        raise ValueError("cognitive_entity_archived")
    draft = await db.scalar(
        select(EnterpriseCognitiveVersion)
        .where(
            EnterpriseCognitiveVersion.entity_id == entity.id,
            EnterpriseCognitiveVersion.status == "draft",
        )
        .order_by(EnterpriseCognitiveVersion.version.desc())
        .limit(1)
    )
    if draft is None:
        max_version = await db.scalar(
            select(func.max(EnterpriseCognitiveVersion.version)).where(
                EnterpriseCognitiveVersion.entity_id == entity.id
            )
        )
        draft = EnterpriseCognitiveVersion(
            id=str(uuid.uuid4()),
            entity_id=entity.id,
            tenant_id=entity.tenant_id,
            workspace_id=entity.workspace_id,
            version=int(max_version or 0) + 1,
            created_by=actor.id,
        )
        db.add(draft)
    for field_name in (
        "classification",
        "summary",
        "mission",
        "vision",
        "values",
        "responsibilities",
        "products_services",
        "operating_principles",
        "terminology",
        "key_contacts",
        "source_refs",
        "context_metadata",
        "effective_from",
        "effective_to",
        "review_due_at",
    ):
        if field_name in values:
            setattr(draft, field_name, values[field_name])
    if draft.classification not in CLASSIFICATIONS:
        raise ValueError("unsupported_cognitive_classification")
    if draft.effective_from and draft.effective_to and draft.effective_to <= draft.effective_from:
        raise ValueError("cognitive_effective_range_invalid")
    await db.flush()
    _add_audit(
        db,
        actor=actor,
        action="enterprise_cognitive_draft_saved",
        resource_id=draft.id,
        payload={"entity_id": entity.id, "version": draft.version},
    )
    return draft


async def publish_cognitive_version(
    db: AsyncSession,
    *,
    entity: EnterpriseCognitiveEntity,
    actor: User,
) -> EnterpriseCognitiveVersion:
    await db.scalar(
        select(EnterpriseCognitiveEntity)
        .where(EnterpriseCognitiveEntity.id == entity.id)
        .with_for_update()
    )
    if entity.status != "active":
        raise ValueError("cognitive_entity_archived")
    draft = await db.scalar(
        select(EnterpriseCognitiveVersion)
        .where(
            EnterpriseCognitiveVersion.entity_id == entity.id,
            EnterpriseCognitiveVersion.status == "draft",
        )
        .order_by(EnterpriseCognitiveVersion.version.desc())
        .limit(1)
    )
    if draft is None:
        raise ValueError("cognitive_draft_not_found")
    if not draft.summary.strip() and not draft.mission.strip():
        raise ValueError("cognitive_profile_requires_summary_or_mission")
    if not draft.source_refs and not entity.knowledge_space_id:
        raise ValueError("cognitive_profile_requires_provenance")
    now = datetime.now(UTC)
    published = list(
        (
            await db.execute(
                select(EnterpriseCognitiveVersion).where(
                    EnterpriseCognitiveVersion.entity_id == entity.id,
                    EnterpriseCognitiveVersion.status == "published",
                )
            )
        ).scalars()
    )
    for previous in published:
        previous.status = "archived"
    if published:
        await db.flush()
    draft.status = "published"
    draft.published_by = actor.id
    draft.published_at = now
    if draft.effective_from is None:
        draft.effective_from = now
    await db.flush()
    _add_audit(
        db,
        actor=actor,
        action="enterprise_cognitive_version_published",
        resource_id=draft.id,
        payload={"entity_id": entity.id, "version": draft.version},
    )
    return draft


async def archive_cognitive_entity(
    db: AsyncSession,
    *,
    entity: EnterpriseCognitiveEntity,
    actor: User,
) -> EnterpriseCognitiveEntity:
    locked = await db.scalar(
        select(EnterpriseCognitiveEntity)
        .where(EnterpriseCognitiveEntity.id == entity.id)
        .with_for_update()
    )
    if locked is None:
        raise ValueError("cognitive_entity_not_found")
    locked.status = "archived"
    drafts = list(
        (
            await db.execute(
                select(EnterpriseCognitiveVersion).where(
                    EnterpriseCognitiveVersion.entity_id == entity.id,
                    EnterpriseCognitiveVersion.status == "draft",
                )
            )
        ).scalars()
    )
    for draft in drafts:
        draft.status = "archived"
    await db.flush()
    _add_audit(
        db,
        actor=actor,
        action="enterprise_cognitive_entity_archived",
        resource_id=entity.id,
        payload={"entity_type": entity.entity_type, "entity_key": entity.entity_key},
    )
    return locked


async def get_scoped_cognitive_entity(
    db: AsyncSession,
    *,
    entity_id: str,
    tenant_id: str,
    workspace_id: str,
) -> EnterpriseCognitiveEntity | None:
    return await db.scalar(
        select(EnterpriseCognitiveEntity).where(
            EnterpriseCognitiveEntity.id == entity_id,
            EnterpriseCognitiveEntity.tenant_id == tenant_id,
            EnterpriseCognitiveEntity.workspace_id == workspace_id,
        )
    )


async def load_enterprise_context(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    org_id: str,
    query: str,
    max_chars: int = 6_000,
) -> EnterpriseContextBundle:
    user = await db.get(User, user_id)
    if user is None:
        return EnterpriseContextBundle()
    now = datetime.now(UTC)
    memberships = list(
        (
            await db.execute(
                select(EnterpriseDirectoryMembership, EnterpriseDirectoryPrincipal)
                .join(
                    EnterpriseDirectoryPrincipal,
                    EnterpriseDirectoryMembership.principal_id == EnterpriseDirectoryPrincipal.id,
                )
                .where(
                    EnterpriseDirectoryMembership.user_id == user_id,
                    EnterpriseDirectoryMembership.tenant_id == tenant_id,
                    EnterpriseDirectoryMembership.workspace_id == workspace_id,
                    EnterpriseDirectoryMembership.status == "active",
                    EnterpriseDirectoryPrincipal.tenant_id == tenant_id,
                    EnterpriseDirectoryPrincipal.workspace_id == workspace_id,
                    EnterpriseDirectoryPrincipal.principal_type == "department",
                    EnterpriseDirectoryPrincipal.status == "active",
                    or_(
                        EnterpriseDirectoryMembership.effective_from.is_(None),
                        EnterpriseDirectoryMembership.effective_from <= now,
                    ),
                    or_(
                        EnterpriseDirectoryMembership.effective_to.is_(None),
                        EnterpriseDirectoryMembership.effective_to > now,
                    ),
                )
            )
        ).all()
    )
    department_principals = await _department_lineage(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        direct=[principal for _, principal in memberships],
    )
    department_ids = {row.id for row in department_principals}
    entity_filters = [
        and_(
            EnterpriseCognitiveEntity.entity_type == "company",
            EnterpriseCognitiveEntity.entity_key == org_id,
        )
    ]
    if department_ids:
        entity_filters.append(
            and_(
                EnterpriseCognitiveEntity.entity_type == "department",
                EnterpriseCognitiveEntity.directory_principal_id.in_(department_ids),
            )
        )
    entity_filter = or_(*entity_filters)
    entities = list(
        (
            await db.execute(
                select(EnterpriseCognitiveEntity).where(
                    EnterpriseCognitiveEntity.tenant_id == tenant_id,
                    EnterpriseCognitiveEntity.workspace_id == workspace_id,
                    EnterpriseCognitiveEntity.status == "active",
                    entity_filter,
                )
            )
        ).scalars()
    )
    if not entities:
        return EnterpriseContextBundle()
    versions = list(
        (
            await db.execute(
                select(EnterpriseCognitiveVersion)
                .where(
                    EnterpriseCognitiveVersion.entity_id.in_([row.id for row in entities]),
                    EnterpriseCognitiveVersion.tenant_id == tenant_id,
                    EnterpriseCognitiveVersion.workspace_id == workspace_id,
                    EnterpriseCognitiveVersion.status == "published",
                    or_(
                        EnterpriseCognitiveVersion.effective_from.is_(None),
                        EnterpriseCognitiveVersion.effective_from <= now,
                    ),
                    or_(
                        EnterpriseCognitiveVersion.effective_to.is_(None),
                        EnterpriseCognitiveVersion.effective_to > now,
                    ),
                )
                .order_by(
                    EnterpriseCognitiveVersion.entity_id,
                    EnterpriseCognitiveVersion.version.desc(),
                )
            )
        ).scalars()
    )
    latest_versions: dict[str, EnterpriseCognitiveVersion] = {}
    for version in versions:
        latest_versions.setdefault(version.entity_id, version)
    access = await resolve_access_context(
        db,
        user=user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    principals_by_id = {row.id: row for row in department_principals}
    rendered: list[dict[str, Any]] = []
    accessible_space_ids = set(access.accessible_space_ids)
    for entity in sorted(
        entities, key=lambda row: (row.entity_type != "company", row.display_name)
    ):
        version = latest_versions.get(entity.id)
        if version is None or not classification_allows(access.clearance, version.classification):
            continue
        principal = principals_by_id.get(entity.directory_principal_id or "")
        knowledge_space_id = str(entity.knowledge_space_id or "") or None
        if knowledge_space_id not in accessible_space_ids:
            knowledge_space_id = None
        rendered.append(
            {
                "entity_id": entity.id,
                "entity_type": entity.entity_type,
                "entity_key": entity.entity_key,
                "display_name": entity.display_name,
                "directory_external_id": principal.external_id if principal else None,
                "knowledge_space_id": knowledge_space_id,
                "version_id": version.id,
                "version": version.version,
                "classification": version.classification,
                "summary": version.summary,
                "mission": version.mission,
                "vision": version.vision,
                "values": list(version.values or []),
                "responsibilities": list(version.responsibilities or []),
                "products_services": list(version.products_services or []),
                "operating_principles": list(version.operating_principles or []),
                "terminology": dict(version.terminology or {}),
                "key_contacts": list(version.key_contacts or []),
            }
        )
    if not rendered:
        return EnterpriseContextBundle()
    prompt = _render_context_prompt(rendered, query=query, max_chars=max_chars)
    space_ids = list(
        dict.fromkeys(
            str(item["knowledge_space_id"]) for item in rendered if item.get("knowledge_space_id")
        )
    )
    return EnterpriseContextBundle(
        prompt=prompt,
        entities=rendered,
        knowledge_space_ids=space_ids,
        requires_grounding=bool(space_ids and ENTERPRISE_GROUNDING_PATTERN.search(query or "")),
    )


async def _validate_cognitive_space(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    space_id: str | None,
    entity_type: str,
) -> KnowledgeSpace | None:
    if not space_id:
        return None
    space = await db.scalar(
        select(KnowledgeSpace).where(
            KnowledgeSpace.id == space_id,
            KnowledgeSpace.tenant_id == tenant_id,
            KnowledgeSpace.workspace_id == workspace_id,
            KnowledgeSpace.status == "active",
        )
    )
    if space is None:
        raise ValueError("knowledge_space_not_found")
    if space.space_type != entity_type:
        raise ValueError("knowledge_space_type_mismatch")
    return space


async def _department_lineage(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    direct: list[EnterpriseDirectoryPrincipal],
) -> list[EnterpriseDirectoryPrincipal]:
    if not direct:
        return []
    selected = {row.id: row for row in direct}
    parent_external_ids = {row.parent_external_id for row in direct if row.parent_external_id}
    for _ in range(8):
        if not parent_external_ids:
            break
        parents = list(
            (
                await db.execute(
                    select(EnterpriseDirectoryPrincipal).where(
                        EnterpriseDirectoryPrincipal.tenant_id == tenant_id,
                        EnterpriseDirectoryPrincipal.workspace_id == workspace_id,
                        EnterpriseDirectoryPrincipal.principal_type == "department",
                        EnterpriseDirectoryPrincipal.status == "active",
                        EnterpriseDirectoryPrincipal.external_id.in_(parent_external_ids),
                    )
                )
            ).scalars()
        )
        next_external_ids: set[str] = set()
        for parent in parents:
            if parent.id in selected:
                continue
            selected[parent.id] = parent
            if parent.parent_external_id:
                next_external_ids.add(parent.parent_external_id)
        parent_external_ids = next_external_ids
    return list(selected.values())


def _render_context_prompt(
    entities: list[dict[str, Any]],
    *,
    query: str,
    max_chars: int,
) -> str:
    lines = [
        "企业基础认知（管理员审核发布，按当前员工组织与密级授权装配）：",
        "这些内容用于理解公司语境、术语和职责边界；涉及制度细节、时效性事实或执行依据时，必须检索绑定的企业知识并保留引用。",
    ]
    detailed = bool(ENTERPRISE_GROUNDING_PATTERN.search(query or ""))
    for item in entities:
        label = "公司" if item["entity_type"] == "company" else "部门"
        lines.append(
            f"\n[{label}] {item['display_name']}（认知版本 v{item['version']}，"
            f"密级 {item['classification']}）"
        )
        for title, field_name in (
            ("简介", "summary"),
            ("使命", "mission"),
            ("愿景", "vision"),
        ):
            value = str(item.get(field_name) or "").strip()
            if value:
                lines.append(f"- {title}：{value}")
        if detailed:
            for title, field_name in (
                ("价值观", "values"),
                ("职责", "responsibilities"),
                ("产品与服务", "products_services"),
                ("经营原则", "operating_principles"),
                ("关键联系人", "key_contacts"),
            ):
                values = [
                    str(value).strip() for value in item.get(field_name) or [] if str(value).strip()
                ]
                if values:
                    lines.append(f"- {title}：" + "；".join(values[:12]))
            terminology = dict(item.get("terminology") or {})
            if terminology:
                terms = [f"{key}={value}" for key, value in list(terminology.items())[:20]]
                lines.append("- 企业术语：" + "；".join(terms))
    rendered = "\n".join(lines)
    return rendered[:max_chars]


def _add_audit(
    db: AsyncSession,
    *,
    actor: User,
    action: str,
    resource_id: str,
    payload: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            id=str(uuid.uuid4()),
            user_id=actor.id,
            action=action,
            resource_type="enterprise_cognition",
            resource_id=resource_id,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
    )
