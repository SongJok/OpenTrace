"""Enterprise admin — tenant, directory, operations, capabilities and compliance."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.admin import get_current_admin_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.security.resource_scope import normalized_tenant_scope
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    EnterpriseDirectoryMembership,
    EnterpriseDirectoryPrincipal,
    EnterpriseDirectorySyncRun,
    User,
)
from services.enterprise_cognition import (
    archive_cognitive_entity,
    cognitive_entity_payload,
    cognitive_version_payload,
    create_cognitive_entity,
    get_scoped_cognitive_entity,
    list_cognitive_entities,
    list_cognitive_versions,
    publish_cognitive_version,
    save_cognitive_draft,
)
from services.enterprise_directory import (
    directory_membership_payload,
    directory_principal_payload,
    directory_sync_run_payload,
    sync_enterprise_directory,
)
from services.enterprise_operations import enterprise_operations_overview
from services.enterprise_workbench_templates import (
    archive_workbench_template,
    create_workbench_template,
    list_workbench_templates,
    update_workbench_template,
    workbench_template_scenario_catalog,
)

router = APIRouter()


class DirectoryPrincipalInput(BaseModel):
    principal_type: Literal["department", "group", "role"]
    external_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=255)
    parent_external_id: str | None = Field(default=None, max_length=128)
    status: Literal["active", "inactive"] = "active"
    attributes: dict[str, Any] = Field(default_factory=dict)


class DirectoryMembershipInput(BaseModel):
    user_email: str = Field(min_length=3, max_length=255)
    principal_type: Literal["department", "group", "role"]
    principal_external_id: str = Field(min_length=1, max_length=128)
    status: Literal["active", "inactive"] = "active"
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DirectorySyncRequest(BaseModel):
    provider: Literal["manual", "scim", "hr", "dingtalk"] = "manual"
    cursor: str | None = Field(default=None, max_length=512)
    authoritative: bool = False
    principals: list[DirectoryPrincipalInput] = Field(default_factory=list, max_length=2000)
    memberships: list[DirectoryMembershipInput] = Field(default_factory=list, max_length=5000)


class CognitiveEntityInput(BaseModel):
    entity_type: Literal["company", "department"]
    display_name: str = Field(min_length=1, max_length=255)
    department_external_id: str | None = Field(default=None, max_length=128)
    knowledge_space_id: str | None = Field(default=None, max_length=36)


class CognitiveDraftInput(BaseModel):
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    summary: str = Field(default="", max_length=12_000)
    mission: str = Field(default="", max_length=8_000)
    vision: str = Field(default="", max_length=8_000)
    values: list[str] = Field(default_factory=list, max_length=100)
    responsibilities: list[str] = Field(default_factory=list, max_length=200)
    products_services: list[str] = Field(default_factory=list, max_length=200)
    operating_principles: list[str] = Field(default_factory=list, max_length=200)
    terminology: dict[str, str] = Field(default_factory=dict)
    key_contacts: list[str] = Field(default_factory=list, max_length=100)
    source_refs: list[str] = Field(default_factory=list, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    review_due_at: datetime | None = None


class WorkbenchTemplateInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    audience_type: Literal["all", "principals"] = "principals"
    principal_ids: list[str] = Field(default_factory=list, max_length=100)
    scenario_ids: list[str] = Field(min_length=1, max_length=20)
    priority: int = Field(default=100, ge=0, le=1000)
    status: Literal["active", "inactive"] = "inactive"


class WorkbenchTemplateUpdateInput(WorkbenchTemplateInput):
    version: int = Field(ge=1)


def _scope(request: Request, user: User) -> tuple[str, str]:
    return normalized_tenant_scope(build_tenant_metadata(request, user_id=user.id))


def _org_id(request: Request, user: User) -> str:
    metadata = build_tenant_metadata(request, user_id=user.id)
    return str(metadata.get("org_id") or metadata.get("tenant_id") or "default")


def _cognition_error(exc: ValueError) -> AppException:
    reason = str(exc)
    messages = {
        "unsupported_cognitive_entity_type": "不支持的企业认知实体类型",
        "department_external_id_required": "部门认知实体必须绑定企业目录部门",
        "department_principal_not_found": "未找到当前租户工作区内的有效部门",
        "knowledge_space_not_found": "未找到当前租户工作区内的有效知识空间",
        "knowledge_space_type_mismatch": "知识空间类型必须与公司或部门认知实体一致",
        "cognitive_entity_not_found": "企业认知实体不存在",
        "cognitive_entity_archived": "企业认知实体已归档，请先重新激活实体绑定",
        "cognitive_draft_not_found": "请先保存企业认知草稿",
        "cognitive_profile_requires_summary_or_mission": "发布前必须填写简介或使命",
        "cognitive_profile_requires_provenance": "发布前必须绑定知识空间或填写来源引用",
        "cognitive_effective_range_invalid": "认知版本失效时间必须晚于生效时间",
        "unsupported_cognitive_classification": "不支持的企业认知密级",
    }
    return AppException(
        ErrorCodes.PARAM_INVALID.code,
        message=messages.get(reason, "企业认知数据校验失败"),
        details={"reason": reason},
    )


def _workbench_template_error(exc: ValueError) -> AppException:
    reason = str(exc)
    if reason == "workbench_template_not_found":
        return AppException(
            ErrorCodes.RESOURCE_NOT_FOUND.code,
            message="组织工作台模板不存在",
            details={"reason": reason},
        )
    if reason == "workbench_template_version_conflict":
        return AppException(
            ErrorCodes.RESOURCE_EXISTS.code,
            message="模板已被其他管理员更新，请刷新后重试",
            details={"reason": reason},
        )
    messages = {
        "unsupported_workbench_audience": "不支持的模板适用范围",
        "unsupported_workbench_template_status": "不支持的模板状态",
        "all_audience_cannot_have_principals": "全体员工模板不能同时绑定目录主体",
        "workbench_template_principal_required": "按组织匹配的模板至少绑定一个目录主体",
        "workbench_template_principal_not_found": "目录主体不存在、未启用或不在当前租户工作区",
        "workbench_template_scenario_required": "模板至少包含一个工作场景",
        "too_many_workbench_template_scenarios": "模板场景数量超过目录上限",
        "workbench_template_name_required": "模板名称不能为空",
    }
    return AppException(
        ErrorCodes.PARAM_INVALID.code,
        message=messages.get(reason.split(":", 1)[0], "组织工作台模板校验失败"),
        details={"reason": reason},
    )


@router.get("/admin/enterprise/operations/overview")
async def operations_overview(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    return await enterprise_operations_overview(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )


@router.get("/admin/enterprise/directory/principals")
async def list_directory_principals(
    request: Request,
    principal_type: Literal["department", "group", "role"] | None = None,
    status: Literal["active", "inactive"] | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    stmt = select(EnterpriseDirectoryPrincipal).where(
        EnterpriseDirectoryPrincipal.tenant_id == tenant_id,
        EnterpriseDirectoryPrincipal.workspace_id == workspace_id,
    )
    if principal_type:
        stmt = stmt.where(EnterpriseDirectoryPrincipal.principal_type == principal_type)
    if status:
        stmt = stmt.where(EnterpriseDirectoryPrincipal.status == status)
    rows = list(
        (
            await db.execute(
                stmt.order_by(
                    EnterpriseDirectoryPrincipal.principal_type,
                    EnterpriseDirectoryPrincipal.display_name,
                ).limit(limit)
            )
        ).scalars()
    )
    return {"items": [directory_principal_payload(row) for row in rows]}


@router.get("/admin/enterprise/directory/memberships")
async def list_directory_memberships(
    request: Request,
    status: Literal["active", "inactive"] | None = None,
    limit: int = Query(default=1000, ge=1, le=5000),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    stmt = (
        select(EnterpriseDirectoryMembership, User, EnterpriseDirectoryPrincipal)
        .join(User, EnterpriseDirectoryMembership.user_id == User.id)
        .join(
            EnterpriseDirectoryPrincipal,
            EnterpriseDirectoryMembership.principal_id == EnterpriseDirectoryPrincipal.id,
        )
        .where(
            EnterpriseDirectoryMembership.tenant_id == tenant_id,
            EnterpriseDirectoryMembership.workspace_id == workspace_id,
            EnterpriseDirectoryPrincipal.tenant_id == tenant_id,
            EnterpriseDirectoryPrincipal.workspace_id == workspace_id,
        )
    )
    if status:
        stmt = stmt.where(EnterpriseDirectoryMembership.status == status)
    rows = (
        await db.execute(
            stmt.order_by(
                EnterpriseDirectoryPrincipal.display_name,
                User.email,
            ).limit(limit)
        )
    ).all()
    return {
        "items": [
            directory_membership_payload(membership, user=user, principal=principal)
            for membership, user, principal in rows
        ]
    }


@router.get("/admin/enterprise/directory/sync-runs")
async def list_directory_sync_runs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    rows = list(
        (
            await db.execute(
                select(EnterpriseDirectorySyncRun)
                .where(
                    EnterpriseDirectorySyncRun.tenant_id == tenant_id,
                    EnterpriseDirectorySyncRun.workspace_id == workspace_id,
                )
                .order_by(EnterpriseDirectorySyncRun.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
    return {"items": [directory_sync_run_payload(row) for row in rows]}


@router.post("/admin/enterprise/directory/sync", status_code=202)
async def sync_directory(
    request: Request,
    payload: DirectorySyncRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    run = await sync_enterprise_directory(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor=current_user,
        provider=payload.provider,
        cursor=payload.cursor,
        authoritative=payload.authoritative,
        principals=[item.model_dump() for item in payload.principals],
        memberships=[item.model_dump() for item in payload.memberships],
    )
    await db.commit()
    await db.refresh(run)
    return directory_sync_run_payload(run)


@router.get("/admin/enterprise/workbench/templates")
async def get_workbench_templates(
    request: Request,
    include_archived: bool = False,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    return {
        "items": await list_workbench_templates(
            db,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            include_archived=include_archived,
        ),
        "scenario_catalog": workbench_template_scenario_catalog(),
    }


@router.post("/admin/enterprise/workbench/templates", status_code=201)
async def post_workbench_template(
    request: Request,
    payload: WorkbenchTemplateInput,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    try:
        result = await create_workbench_template(
            db,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor=current_user,
            **payload.model_dump(),
        )
    except ValueError as exc:
        raise _workbench_template_error(exc) from exc
    await db.commit()
    return result


@router.put("/admin/enterprise/workbench/templates/{template_id}")
async def put_workbench_template(
    template_id: str,
    request: Request,
    payload: WorkbenchTemplateUpdateInput,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    try:
        result = await update_workbench_template(
            db,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor=current_user,
            template_id=template_id,
            **payload.model_dump(),
        )
    except ValueError as exc:
        raise _workbench_template_error(exc) from exc
    await db.commit()
    return result


@router.delete("/admin/enterprise/workbench/templates/{template_id}")
async def delete_workbench_template(
    template_id: str,
    request: Request,
    version: int = Query(ge=1),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    try:
        result = await archive_workbench_template(
            db,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor=current_user,
            template_id=template_id,
            version=version,
        )
    except ValueError as exc:
        raise _workbench_template_error(exc) from exc
    await db.commit()
    return result


@router.get("/admin/enterprise/cognition/entities")
async def get_cognitive_entities(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    return {
        "vision": "成为企业级的工作台、最懂公司的 AI",
        "items": await list_cognitive_entities(
            db,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            org_id=_org_id(request, current_user),
        ),
    }


@router.post("/admin/enterprise/cognition/entities", status_code=201)
async def upsert_cognitive_entity(
    request: Request,
    payload: CognitiveEntityInput,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    try:
        entity = await create_cognitive_entity(
            db,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            org_id=_org_id(request, current_user),
            actor=current_user,
            entity_type=payload.entity_type,
            display_name=payload.display_name,
            department_external_id=payload.department_external_id,
            knowledge_space_id=payload.knowledge_space_id,
        )
    except ValueError as exc:
        raise _cognition_error(exc) from exc
    await db.commit()
    await db.refresh(entity)
    return cognitive_entity_payload(entity)


@router.put("/admin/enterprise/cognition/entities/{entity_id}/draft")
async def put_cognitive_draft(
    entity_id: str,
    request: Request,
    payload: CognitiveDraftInput,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    entity = await get_scoped_cognitive_entity(
        db,
        entity_id=entity_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if entity is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="企业认知实体不存在")
    values = payload.model_dump()
    values["context_metadata"] = values.pop("metadata")
    try:
        version = await save_cognitive_draft(
            db,
            entity=entity,
            actor=current_user,
            values=values,
        )
    except ValueError as exc:
        raise _cognition_error(exc) from exc
    await db.commit()
    await db.refresh(version)
    return cognitive_version_payload(version) or {}


@router.get("/admin/enterprise/cognition/entities/{entity_id}/versions")
async def get_cognitive_versions(
    entity_id: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    entity = await get_scoped_cognitive_entity(
        db,
        entity_id=entity_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if entity is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="企业认知实体不存在")
    return {
        "items": await list_cognitive_versions(
            db,
            entity_id=entity.id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
    }


@router.post("/admin/enterprise/cognition/entities/{entity_id}/archive")
async def archive_cognitive_profile(
    entity_id: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    entity = await get_scoped_cognitive_entity(
        db,
        entity_id=entity_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if entity is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="企业认知实体不存在")
    try:
        archived = await archive_cognitive_entity(db, entity=entity, actor=current_user)
    except ValueError as exc:
        raise _cognition_error(exc) from exc
    await db.commit()
    await db.refresh(archived)
    return cognitive_entity_payload(archived)


@router.post("/admin/enterprise/cognition/entities/{entity_id}/publish")
async def publish_cognitive_draft(
    entity_id: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    entity = await get_scoped_cognitive_entity(
        db,
        entity_id=entity_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if entity is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="企业认知实体不存在")
    try:
        version = await publish_cognitive_version(
            db,
            entity=entity,
            actor=current_user,
        )
    except ValueError as exc:
        raise _cognition_error(exc) from exc
    await db.commit()
    await db.refresh(version)
    return cognitive_version_payload(version) or {}


@router.get("/admin/enterprise/tenants")
async def list_enterprise_tenants(
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    from tenant.tenant_manager import TenantManager

    tm = TenantManager()
    return {"tenants": [t.to_dict() for t in tm.list_all()]}


@router.get("/admin/enterprise/control-plane/health")
async def control_plane_health(
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    from control_plane.control_plane import get_enterprise_control_plane
    from kernel.capability_runtime.capability_os import get_capability_os

    cp = get_enterprise_control_plane()
    d = cp.evaluate_turn(session_id="health-check")
    return {
        "control_plane": {"sample_decision_allowed": d.allowed},
        "capability_marketplace_count": len(get_capability_os().list_marketplace()),
    }


@router.get("/admin/enterprise/capabilities/marketplace")
async def capability_marketplace(
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    from kernel.capability_runtime.capability_os import get_capability_os

    return {"products": get_capability_os().list_marketplace()}


@router.get("/admin/enterprise/compliance/audit")
async def compliance_audit_recent(
    tenant_id: str = Query("default"),
    limit: int = Query(50, le=200),
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    from governance.compliance_audit_store import list_recent_events_from_db

    return {"events": await list_recent_events_from_db(tenant_id, limit=limit)}


@router.get("/admin/enterprise/usage/{tenant_id}")
async def tenant_usage_summary(
    tenant_id: str,
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    from tenant.billing_manager import BillingManager
    from tenant.usage_metering import get_usage_metering

    usage = await get_usage_metering().tenant_summary_async(tenant_id)
    billing = BillingManager().snapshot(tenant_id)
    return {"usage": usage, "billing": billing}


@router.post("/admin/enterprise/tenants/{tenant_id}/quota")
async def set_tenant_quota(
    tenant_id: str,
    body: dict[str, Any],
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    from control_plane.control_plane import get_enterprise_control_plane
    from tenant.tenant_context import resolve_tenant_context

    ctx = resolve_tenant_context(
        tenant_id=tenant_id,
        org_id=str(body.get("org_id") or tenant_id),
        workspace_id=str(body.get("workspace_id") or "default"),
    )
    get_enterprise_control_plane().set_quota_limits(
        ctx,
        daily_turns=int(body.get("daily_turns", 10_000)),
        daily_cost=float(body.get("daily_cost", 500.0)),
    )
    return {"ok": True, "isolation_key": ctx.isolation_key()}
