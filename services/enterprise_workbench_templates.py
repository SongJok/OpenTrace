"""组织级工作台模板的治理、目录匹配与员工投影。"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    AuditLog,
    EnterpriseDirectoryMembership,
    EnterpriseDirectoryPrincipal,
    EnterpriseWorkbenchTemplate,
    EnterpriseWorkbenchTemplateTarget,
    User,
)
from services.enterprise_scenarios import ENTERPRISE_SCENARIO_CATALOG

AUDIENCE_TYPES = {"all", "principals"}
TEMPLATE_STATUSES = {"active", "inactive"}
SCENARIO_IDS = {item.id for item in ENTERPRISE_SCENARIO_CATALOG}


def workbench_template_scenario_catalog() -> list[dict[str, str]]:
    return [
        {
            "id": item.id,
            "category": item.category,
            "title": item.title,
            "description": item.description,
        }
        for item in ENTERPRISE_SCENARIO_CATALOG
    ]


def _validate_configuration(
    *,
    audience_type: str,
    principal_ids: list[str],
    scenario_ids: list[str],
    status: str,
) -> tuple[list[str], list[str]]:
    if audience_type not in AUDIENCE_TYPES:
        raise ValueError("unsupported_workbench_audience")
    if status not in TEMPLATE_STATUSES:
        raise ValueError("unsupported_workbench_template_status")

    normalized_principals = list(
        dict.fromkeys(item.strip() for item in principal_ids if item.strip())
    )
    normalized_scenarios = list(
        dict.fromkeys(item.strip() for item in scenario_ids if item.strip())
    )
    if audience_type == "all" and normalized_principals:
        raise ValueError("all_audience_cannot_have_principals")
    if audience_type == "principals" and not normalized_principals:
        raise ValueError("workbench_template_principal_required")
    if not normalized_scenarios:
        raise ValueError("workbench_template_scenario_required")
    if len(normalized_scenarios) > len(ENTERPRISE_SCENARIO_CATALOG):
        raise ValueError("too_many_workbench_template_scenarios")
    if unknown := set(normalized_scenarios) - SCENARIO_IDS:
        raise ValueError(f"unknown_workbench_scenario:{sorted(unknown)[0]}")
    return normalized_principals, normalized_scenarios


async def _load_scoped_principals(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    principal_ids: list[str],
    require_active: bool = True,
) -> dict[str, EnterpriseDirectoryPrincipal]:
    if not principal_ids:
        return {}
    stmt = select(EnterpriseDirectoryPrincipal).where(
        EnterpriseDirectoryPrincipal.id.in_(principal_ids),
        EnterpriseDirectoryPrincipal.tenant_id == tenant_id,
        EnterpriseDirectoryPrincipal.workspace_id == workspace_id,
    )
    if require_active:
        stmt = stmt.where(EnterpriseDirectoryPrincipal.status == "active")
    rows = list((await db.execute(stmt)).scalars())
    result = {row.id: row for row in rows}
    if set(principal_ids) != set(result):
        raise ValueError("workbench_template_principal_not_found")
    return result


async def _target_ids_by_template(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    template_ids: list[str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    if not template_ids:
        return result
    rows = list(
        (
            await db.execute(
                select(EnterpriseWorkbenchTemplateTarget).where(
                    EnterpriseWorkbenchTemplateTarget.template_id.in_(template_ids),
                    EnterpriseWorkbenchTemplateTarget.tenant_id == tenant_id,
                    EnterpriseWorkbenchTemplateTarget.workspace_id == workspace_id,
                )
            )
        ).scalars()
    )
    for row in rows:
        result[row.template_id].append(row.principal_id)
    return result


def workbench_template_payload(
    row: EnterpriseWorkbenchTemplate,
    *,
    target_ids: list[str],
    principals: dict[str, EnterpriseDirectoryPrincipal],
) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "audience_type": row.audience_type,
        "principal_ids": target_ids,
        "principals": [
            {
                "id": principals[item].id,
                "principal_type": principals[item].principal_type,
                "external_id": principals[item].external_id,
                "display_name": principals[item].display_name,
            }
            for item in target_ids
            if item in principals
        ],
        "scenario_ids": list(row.scenario_ids or []),
        "priority": row.priority,
        "status": row.status,
        "version": row.version,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def list_workbench_templates(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    stmt = select(EnterpriseWorkbenchTemplate).where(
        EnterpriseWorkbenchTemplate.tenant_id == tenant_id,
        EnterpriseWorkbenchTemplate.workspace_id == workspace_id,
    )
    if not include_archived:
        stmt = stmt.where(EnterpriseWorkbenchTemplate.status != "archived")
    rows = list(
        (
            await db.execute(
                stmt.order_by(
                    EnterpriseWorkbenchTemplate.priority.desc(),
                    EnterpriseWorkbenchTemplate.created_at,
                )
            )
        ).scalars()
    )
    target_map = await _target_ids_by_template(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        template_ids=[row.id for row in rows],
    )
    target_ids = list(dict.fromkeys(item for values in target_map.values() for item in values))
    principals = await _load_scoped_principals(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        principal_ids=target_ids,
        require_active=False,
    )
    return [
        workbench_template_payload(
            row,
            target_ids=target_map.get(row.id, []),
            principals=principals,
        )
        for row in rows
    ]


def _add_audit(
    db: AsyncSession,
    *,
    actor: User,
    action: str,
    template: EnterpriseWorkbenchTemplate,
    principal_ids: list[str],
) -> None:
    db.add(
        AuditLog(
            id=str(uuid.uuid4()),
            user_id=actor.id,
            action=action,
            resource_type="enterprise_workbench_template",
            resource_id=template.id,
            payload_json=json.dumps(
                {
                    "tenant_id": template.tenant_id,
                    "workspace_id": template.workspace_id,
                    "name": template.name,
                    "audience_type": template.audience_type,
                    "principal_ids": principal_ids,
                    "scenario_ids": list(template.scenario_ids or []),
                    "priority": template.priority,
                    "status": template.status,
                    "version": template.version,
                },
                ensure_ascii=False,
            ),
        )
    )


async def create_workbench_template(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    actor: User,
    name: str,
    description: str,
    audience_type: str,
    principal_ids: list[str],
    scenario_ids: list[str],
    priority: int,
    status: str,
) -> dict[str, Any]:
    if not name.strip():
        raise ValueError("workbench_template_name_required")
    principal_ids, scenario_ids = _validate_configuration(
        audience_type=audience_type,
        principal_ids=principal_ids,
        scenario_ids=scenario_ids,
        status=status,
    )
    principals = await _load_scoped_principals(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        principal_ids=principal_ids,
    )
    row = EnterpriseWorkbenchTemplate(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        name=name.strip(),
        description=description.strip(),
        audience_type=audience_type,
        scenario_ids=scenario_ids,
        priority=priority,
        status=status,
        version=1,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(row)
    await db.flush()
    for principal_id in principal_ids:
        db.add(
            EnterpriseWorkbenchTemplateTarget(
                id=str(uuid.uuid4()),
                template_id=row.id,
                principal_id=principal_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
        )
    _add_audit(
        db,
        actor=actor,
        action="enterprise_workbench_template_created",
        template=row,
        principal_ids=principal_ids,
    )
    await db.flush()
    return workbench_template_payload(row, target_ids=principal_ids, principals=principals)


async def _get_scoped_template(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    template_id: str,
) -> EnterpriseWorkbenchTemplate:
    row = await db.scalar(
        select(EnterpriseWorkbenchTemplate)
        .where(
            EnterpriseWorkbenchTemplate.id == template_id,
            EnterpriseWorkbenchTemplate.tenant_id == tenant_id,
            EnterpriseWorkbenchTemplate.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if row is None or row.status == "archived":
        raise ValueError("workbench_template_not_found")
    return row


async def update_workbench_template(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    actor: User,
    template_id: str,
    version: int,
    name: str,
    description: str,
    audience_type: str,
    principal_ids: list[str],
    scenario_ids: list[str],
    priority: int,
    status: str,
) -> dict[str, Any]:
    if not name.strip():
        raise ValueError("workbench_template_name_required")
    principal_ids, scenario_ids = _validate_configuration(
        audience_type=audience_type,
        principal_ids=principal_ids,
        scenario_ids=scenario_ids,
        status=status,
    )
    row = await _get_scoped_template(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        template_id=template_id,
    )
    if row.version != version:
        raise ValueError("workbench_template_version_conflict")
    principals = await _load_scoped_principals(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        principal_ids=principal_ids,
    )
    row.name = name.strip()
    row.description = description.strip()
    row.audience_type = audience_type
    row.scenario_ids = scenario_ids
    row.priority = priority
    row.status = status
    row.updated_by = actor.id
    row.updated_at = datetime.now(UTC)
    row.version += 1
    await db.execute(
        delete(EnterpriseWorkbenchTemplateTarget).where(
            EnterpriseWorkbenchTemplateTarget.template_id == row.id,
            EnterpriseWorkbenchTemplateTarget.tenant_id == tenant_id,
            EnterpriseWorkbenchTemplateTarget.workspace_id == workspace_id,
        )
    )
    for principal_id in principal_ids:
        db.add(
            EnterpriseWorkbenchTemplateTarget(
                id=str(uuid.uuid4()),
                template_id=row.id,
                principal_id=principal_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
        )
    _add_audit(
        db,
        actor=actor,
        action="enterprise_workbench_template_updated",
        template=row,
        principal_ids=principal_ids,
    )
    await db.flush()
    return workbench_template_payload(row, target_ids=principal_ids, principals=principals)


async def archive_workbench_template(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    actor: User,
    template_id: str,
    version: int,
) -> dict[str, Any]:
    row = await _get_scoped_template(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        template_id=template_id,
    )
    if row.version != version:
        raise ValueError("workbench_template_version_conflict")
    target_map = await _target_ids_by_template(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        template_ids=[row.id],
    )
    principal_ids = target_map.get(row.id, [])
    principals = await _load_scoped_principals(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        principal_ids=principal_ids,
        require_active=False,
    )
    row.status = "archived"
    row.updated_by = actor.id
    row.updated_at = datetime.now(UTC)
    row.version += 1
    _add_audit(
        db,
        actor=actor,
        action="enterprise_workbench_template_archived",
        template=row,
        principal_ids=principal_ids,
    )
    await db.flush()
    return workbench_template_payload(row, target_ids=principal_ids, principals=principals)


async def resolve_user_workbench_templates(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """解析员工的直接目录关系和部门祖先，不扩大任何资源访问权限。"""

    effective_at = now or datetime.now(UTC)
    direct_principals = list(
        (
            await db.execute(
                select(EnterpriseDirectoryPrincipal)
                .join(
                    EnterpriseDirectoryMembership,
                    EnterpriseDirectoryMembership.principal_id == EnterpriseDirectoryPrincipal.id,
                )
                .where(
                    EnterpriseDirectoryMembership.user_id == user_id,
                    EnterpriseDirectoryMembership.tenant_id == tenant_id,
                    EnterpriseDirectoryMembership.workspace_id == workspace_id,
                    EnterpriseDirectoryMembership.status == "active",
                    or_(
                        EnterpriseDirectoryMembership.effective_from.is_(None),
                        EnterpriseDirectoryMembership.effective_from <= effective_at,
                    ),
                    or_(
                        EnterpriseDirectoryMembership.effective_to.is_(None),
                        EnterpriseDirectoryMembership.effective_to > effective_at,
                    ),
                    EnterpriseDirectoryPrincipal.tenant_id == tenant_id,
                    EnterpriseDirectoryPrincipal.workspace_id == workspace_id,
                    EnterpriseDirectoryPrincipal.status == "active",
                )
            )
        ).scalars()
    )
    principal_by_id = {row.id: row for row in direct_principals}
    effective_ids = {row.id for row in direct_principals}
    inherited_ids: set[str] = set()
    seen_department_ids = {
        row.external_id for row in direct_principals if row.principal_type == "department"
    }
    pending_parent_ids = {
        row.parent_external_id
        for row in direct_principals
        if row.principal_type == "department" and row.parent_external_id
    }
    while pending_parent_ids:
        parent_rows = list(
            (
                await db.execute(
                    select(EnterpriseDirectoryPrincipal).where(
                        EnterpriseDirectoryPrincipal.tenant_id == tenant_id,
                        EnterpriseDirectoryPrincipal.workspace_id == workspace_id,
                        EnterpriseDirectoryPrincipal.principal_type == "department",
                        EnterpriseDirectoryPrincipal.external_id.in_(pending_parent_ids),
                        EnterpriseDirectoryPrincipal.status == "active",
                    )
                )
            ).scalars()
        )
        pending_parent_ids = set()
        for parent in parent_rows:
            if parent.external_id in seen_department_ids:
                continue
            seen_department_ids.add(parent.external_id)
            principal_by_id[parent.id] = parent
            effective_ids.add(parent.id)
            inherited_ids.add(parent.id)
            if parent.parent_external_id and parent.parent_external_id not in seen_department_ids:
                pending_parent_ids.add(parent.parent_external_id)

    templates = list(
        (
            await db.execute(
                select(EnterpriseWorkbenchTemplate)
                .where(
                    EnterpriseWorkbenchTemplate.tenant_id == tenant_id,
                    EnterpriseWorkbenchTemplate.workspace_id == workspace_id,
                    EnterpriseWorkbenchTemplate.status == "active",
                )
                .order_by(
                    EnterpriseWorkbenchTemplate.priority.desc(),
                    EnterpriseWorkbenchTemplate.created_at,
                )
            )
        ).scalars()
    )
    target_map = await _target_ids_by_template(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        template_ids=[row.id for row in templates],
    )
    matched: list[dict[str, Any]] = []
    for row in templates:
        target_ids = target_map.get(row.id, [])
        matching_ids = effective_ids.intersection(target_ids)
        if row.audience_type != "all" and not matching_ids:
            continue
        matched.append(
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "priority": row.priority,
                "scenario_ids": list(row.scenario_ids or []),
                "matched_principals": [
                    principal_by_id[item].display_name
                    for item in target_ids
                    if item in matching_ids and item in principal_by_id
                ],
            }
        )

    principal_projection = [
        {
            "id": row.id,
            "principal_type": row.principal_type,
            "display_name": row.display_name,
            "inherited": row.id in inherited_ids,
        }
        for row in principal_by_id.values()
    ]
    principal_projection.sort(key=lambda item: (bool(item["inherited"]), str(item["display_name"])))
    return matched, principal_projection
