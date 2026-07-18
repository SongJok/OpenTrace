"""Governed knowledge assets, compilation and health APIs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import normalized_tenant_scope, scoped_documents_statement
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    Document,
    KnowledgeClaim,
    KnowledgeCompilationJob,
    KnowledgeFeedback,
    KnowledgeLintIssue,
    KnowledgeMergeCase,
    KnowledgePage,
    KnowledgeRelation,
    KnowledgeRule,
    KnowledgeSource,
    KnowledgeSourceVersion,
    Project,
    User,
)
from knowledge.domain import KnowledgeStatus, source_status_during_refresh
from knowledge.evolution import build_evolution_proposal
from knowledge.graph import build_project_graph, link_project_pages
from knowledge.jobs import enqueue_document_compile
from knowledge.lint import run_knowledge_lint
from knowledge.merge import resolve_merge_case as apply_merge_case
from knowledge.trace import trace_knowledge_assets

router = APIRouter()


class KnowledgeFeedbackRequest(BaseModel):
    target_type: str
    target_id: str
    feedback_type: str
    score: float | None = None
    correction: str | None = None
    session_id: str | None = None


class KnowledgeRuleRequest(BaseModel):
    rule_key: str
    project_id: str | None = None
    rule_type: str = "schema"
    schema_json: dict = Field(default_factory=dict)
    instructions: str | None = None
    provenance: dict = Field(default_factory=dict)


class KnowledgeTraceRequest(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=100)


@router.get("/knowledge/sources")
async def list_knowledge_sources(
    http_request: Request,
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    stmt = select(KnowledgeSource).where(
        KnowledgeSource.owner_id == current_user.id,
        KnowledgeSource.tenant_id == tenant_id,
        KnowledgeSource.workspace_id == workspace_id,
    )
    if project_id:
        stmt = stmt.where(KnowledgeSource.project_id == project_id)
    rows = (
        await db.execute(
            stmt.order_by(KnowledgeSource.updated_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "document_id": row.document_id,
            "title": row.title,
            "source_type": row.source_type,
            "authority": row.authority,
            "status": row.status,
            "project_id": row.project_id,
            "active_version_id": row.active_version_id,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


@router.get("/knowledge/sources/{source_id}/versions")
async def list_knowledge_source_versions(
    http_request: Request,
    source_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    source = await db.scalar(select(KnowledgeSource).where(
        KnowledgeSource.id == source_id, KnowledgeSource.owner_id == current_user.id,
        KnowledgeSource.tenant_id == tenant_id, KnowledgeSource.workspace_id == workspace_id,
    ))
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Knowledge source not found")
    rows = (await db.execute(select(KnowledgeSourceVersion).where(
        KnowledgeSourceVersion.source_id == source.id,
    ).order_by(KnowledgeSourceVersion.version_number.desc()))).scalars().all()
    return [{
        "id": row.id, "version_number": row.version_number, "status": row.status,
        "content_hash": row.content_hash, "compiler_version": row.compiler_version,
        "raw_metadata": row.raw_metadata, "compiled_at": row.compiled_at.isoformat() if row.compiled_at else None,
        "active": row.id == source.active_version_id,
    } for row in rows]


@router.post("/knowledge/trace")
async def trace_knowledge(
    http_request: Request,
    req: KnowledgeTraceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    refs = await trace_knowledge_assets(
        db, ids=req.ids, tenant_id=tenant_id, workspace_id=workspace_id, owner_id=current_user.id,
    )
    return {"evidence_refs": refs, "count": len(refs)}


@router.get("/knowledge/rules")
async def list_knowledge_rules(
    http_request: Request,
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    stmt = select(KnowledgeRule).where(
        KnowledgeRule.owner_id == current_user.id,
        KnowledgeRule.tenant_id == tenant_id,
        KnowledgeRule.workspace_id == workspace_id,
    )
    if project_id:
        stmt = stmt.where(KnowledgeRule.project_id == project_id)
    rows = (await db.execute(stmt.order_by(KnowledgeRule.rule_key.asc(), KnowledgeRule.version.desc()))).scalars().all()
    return [{
        "id": row.id, "rule_key": row.rule_key, "version": row.version,
        "rule_type": row.rule_type, "status": row.status, "schema": row.schema_json,
        "instructions": row.instructions, "provenance": row.provenance,
        "project_id": row.project_id,
    } for row in rows]


@router.post("/knowledge/rules")
async def create_knowledge_rule(
    http_request: Request,
    req: KnowledgeRuleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    if req.project_id:
        project = await db.scalar(select(Project.id).where(
            Project.id == req.project_id, Project.user_id == current_user.id,
            Project.tenant_id == tenant_id, Project.workspace_id == workspace_id,
            Project.archived_at.is_(None),
        ))
        if project is None:
            raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Project not found")
    allowed_keys = {
        "summary_length", "content_limit", "min_claim_length", "max_claims_per_page",
        "page_type_keywords", "required_page_fields", "required_claim_fields",
        "required_relation_fields", "allowed_page_types",
    }
    unknown = sorted(set(req.schema_json) - allowed_keys)
    if unknown:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=f"Unsupported orchestration fields: {', '.join(unknown)}")
    latest = await db.scalar(select(KnowledgeRule).where(
        KnowledgeRule.owner_id == current_user.id,
        KnowledgeRule.tenant_id == tenant_id,
        KnowledgeRule.workspace_id == workspace_id,
        KnowledgeRule.rule_key == req.rule_key,
    ).order_by(KnowledgeRule.version.desc()))
    version = (latest.version + 1) if latest else 1
    row = KnowledgeRule(
        id=str(uuid.uuid4()), owner_id=current_user.id, tenant_id=tenant_id, workspace_id=workspace_id,
        project_id=req.project_id, rule_key=req.rule_key, version=version,
        rule_type=req.rule_type, schema_json=req.schema_json,
        instructions=req.instructions, provenance={**req.provenance, "created_via": "knowledge_api"},
        created_by=current_user.id,
    )
    db.add(row)
    await db.commit()
    return {"id": row.id, "rule_key": row.rule_key, "version": row.version, "status": row.status, "project_id": row.project_id}


@router.post("/knowledge/rules/{rule_id}/approve")
async def approve_knowledge_rule(
    http_request: Request,
    rule_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    row = await db.scalar(select(KnowledgeRule).where(
        KnowledgeRule.id == rule_id, KnowledgeRule.owner_id == current_user.id,
        KnowledgeRule.tenant_id == tenant_id, KnowledgeRule.workspace_id == workspace_id,
    ))
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Knowledge rule not found")
    previous = (await db.execute(select(KnowledgeRule).where(
        KnowledgeRule.owner_id == current_user.id, KnowledgeRule.tenant_id == tenant_id,
        KnowledgeRule.workspace_id == workspace_id, KnowledgeRule.rule_key == row.rule_key,
        KnowledgeRule.project_id == row.project_id,
        KnowledgeRule.status == "approved", KnowledgeRule.id != row.id,
    ))).scalars().all()
    for item in previous:
        item.status = "archived"
    row.status = "approved"
    row.approved_by = current_user.id
    row.approved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"approved": True, "rule_key": row.rule_key, "version": row.version}


@router.get("/knowledge/pages")
async def list_knowledge_pages(
    http_request: Request,
    source_id: str | None = None,
    limit: int = 50,
    status: str | None = "published",
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    stmt = (
        select(KnowledgePage, KnowledgeSource, KnowledgeSourceVersion)
        .join(KnowledgeSourceVersion, KnowledgePage.source_version_id == KnowledgeSourceVersion.id)
        .join(KnowledgeSource, KnowledgeSourceVersion.source_id == KnowledgeSource.id)
        .where(
            KnowledgePage.owner_id == current_user.id,
            KnowledgePage.tenant_id == tenant_id,
            KnowledgePage.workspace_id == workspace_id,
        )
    )
    if status:
        stmt = stmt.where(KnowledgePage.status == status)
        if status == KnowledgeStatus.PUBLISHED.value:
            stmt = stmt.where(KnowledgeSource.active_version_id == KnowledgeSourceVersion.id)
    if source_id:
        stmt = stmt.where(KnowledgeSource.id == source_id)
    if project_id:
        stmt = stmt.where(KnowledgeSource.project_id == project_id)
    rows = (
        await db.execute(
            stmt.order_by(
                KnowledgeSourceVersion.version_number.desc(),
                KnowledgePage.title.asc(),
            ).limit(max(1, min(limit, 200)))
        )
    ).all()
    return [
        {
            "id": page.id,
            "source_id": source.id,
            "source_version_id": version.id,
            "version_number": version.version_number,
            "title": page.title,
            "type": page.page_type,
            "summary": page.summary,
            "authority": page.authority,
            "status": page.status,
            "metadata": page.page_metadata,
        }
        for page, source, version in rows
    ]


@router.post("/knowledge/documents/{document_id}/compile")
async def compile_document(
    http_request: Request,
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    doc = await db.scalar(
        scoped_documents_statement(
            user_id=current_user.id,
            tenant_metadata=build_tenant_metadata(http_request, user_id=current_user.id),
            document_id=document_id,
        )
    )
    if doc is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Document not found")
    if doc.status != "ready":
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Document is not ready for compilation")
    result = await enqueue_document_compile(document_id)
    return {"accepted": True, **result}


@router.get("/knowledge/jobs")
async def list_knowledge_jobs(
    http_request: Request,
    status: str | None = None,
    limit: int = 50,
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Inspect durable compiler jobs for operational visibility."""
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    conditions = [
        KnowledgeCompilationJob.owner_id == current_user.id,
        KnowledgeCompilationJob.tenant_id == tenant_id,
        KnowledgeCompilationJob.workspace_id == workspace_id,
    ]
    if status:
        conditions.append(KnowledgeCompilationJob.status == status)
    if project_id:
        conditions.append(KnowledgeCompilationJob.project_id == project_id)
    rows = (
        await db.execute(
            select(KnowledgeCompilationJob)
            .where(*conditions)
            .order_by(KnowledgeCompilationJob.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "source_id": row.source_id,
            "source_version_id": row.source_version_id,
            "status": row.status,
            "project_id": row.project_id,
            "compiler_version": row.compiler_version,
            "error": row.error,
            "result": row.result_metadata,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.get("/knowledge/graph")
async def get_knowledge_graph(
    http_request: Request,
    network: str = "entity",
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(http_request, user_id=current_user.id)
    )
    if project_id:
        project = await db.scalar(
            select(Project.id).where(
                Project.id == project_id,
                Project.user_id == current_user.id,
                Project.tenant_id == tenant_id,
                Project.workspace_id == workspace_id,
                Project.archived_at.is_(None),
            )
        )
        if project is None:
            raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Project not found")
    graph = await build_project_graph(
        db,
        owner_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        network=network,
    )
    return {**graph, "project_id": project_id}


@router.post("/knowledge/orchestrate")
async def orchestrate_knowledge(
    http_request: Request,
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Queue all ready project documents and refresh current cross-document links."""
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(http_request, user_id=current_user.id)
    )
    if project_id:
        project = await db.scalar(
            select(Project.id).where(
                Project.id == project_id,
                Project.user_id == current_user.id,
                Project.tenant_id == tenant_id,
                Project.workspace_id == workspace_id,
                Project.archived_at.is_(None),
            )
        )
        if project is None:
            raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Project not found")
    doc_stmt = scoped_documents_statement(
        user_id=current_user.id,
        tenant_metadata={"tenant_id": tenant_id, "workspace_id": workspace_id},
        project_id=project_id,
    ).where(Document.status == "ready")
    documents = (await db.execute(doc_stmt)).scalars().all()
    queued = 0
    for document in documents:
        result = await enqueue_document_compile(document.id)
        if result.get("status") == "queued" and not result.get("deduplicated"):
            queued += 1
    linked = await link_project_pages(
        db,
        owner_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    await db.commit()
    return {"accepted": True, "documents": len(documents), "jobs_queued": queued, **linked}


@router.post("/knowledge/jobs/{job_id}/retry")
async def retry_knowledge_job(
    http_request: Request,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    job = await db.scalar(
        select(KnowledgeCompilationJob).where(
            KnowledgeCompilationJob.id == job_id,
            KnowledgeCompilationJob.owner_id == current_user.id,
            KnowledgeCompilationJob.tenant_id == tenant_id,
            KnowledgeCompilationJob.workspace_id == workspace_id,
        )
    )
    if job is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Knowledge job not found")
    if job.status not in {"failed", "succeeded"}:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Only completed jobs can be retried")
    source = await db.get(KnowledgeSource, job.source_id)
    if source is None or not source.document_id:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Knowledge source has no document")
    job.status = "pending"
    job.error = None
    job.started_at = None
    job.completed_at = None
    job.result_metadata = {**(job.result_metadata or {}), "retry_requested_at": datetime.now(timezone.utc).isoformat()}
    source.status = source_status_during_refresh(
        source.active_version_id,
        KnowledgeStatus.COMPILING,
    )
    await db.commit()
    return {"accepted": True, "job_id": job.id, "document_id": source.document_id, "status": "pending"}


@router.post("/knowledge/lint")
async def lint_knowledge(
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    result = await run_knowledge_lint(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        owner_id=current_user.id,
    )
    await db.commit()
    return result


@router.get("/knowledge/evolution/proposal")
async def knowledge_evolution_proposal(
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    result = await build_evolution_proposal(
        db, tenant_id=tenant_id, workspace_id=workspace_id, owner_id=current_user.id
    )
    await db.commit()
    return result


@router.get("/knowledge/observations")
async def list_knowledge_observations(
    http_request: Request,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    from infra.storage.models import KnowledgeObservation
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    rows = (await db.execute(select(KnowledgeObservation).where(
        KnowledgeObservation.owner_id == current_user.id,
        KnowledgeObservation.tenant_id == tenant_id,
        KnowledgeObservation.workspace_id == workspace_id,
    ).order_by(KnowledgeObservation.created_at.desc()).limit(max(1, min(limit, 500))))).scalars().all()
    return [{
        "id": row.id, "metric": row.metric, "value": row.value,
        "dimensions": row.dimensions, "trigger": row.trigger,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    } for row in rows]


@router.get("/knowledge/merge-cases")
async def list_knowledge_merge_cases(
    http_request: Request,
    status: str = "open",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    rows = (await db.execute(select(KnowledgeMergeCase).where(
        KnowledgeMergeCase.owner_id == current_user.id,
        KnowledgeMergeCase.tenant_id == tenant_id,
        KnowledgeMergeCase.workspace_id == workspace_id,
        KnowledgeMergeCase.status == status,
    ).order_by(KnowledgeMergeCase.created_at.desc()))).scalars().all()
    return [{
        "id": row.id, "entity_key": row.entity_key, "conflict_type": row.conflict_type,
        "candidate_ids": row.candidate_ids, "status": row.status, "resolution": row.resolution,
    } for row in rows]


@router.post("/knowledge/merge-cases/{case_id}/resolve")
async def resolve_knowledge_merge_case(
    http_request: Request,
    case_id: str,
    resolution: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    row = await db.scalar(select(KnowledgeMergeCase).where(
        KnowledgeMergeCase.id == case_id, KnowledgeMergeCase.owner_id == current_user.id,
        KnowledgeMergeCase.tenant_id == tenant_id, KnowledgeMergeCase.workspace_id == workspace_id,
    ))
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Knowledge merge case not found")
    try:
        result = await apply_merge_case(
            db, case_id=case_id, owner_id=current_user.id, tenant_id=tenant_id,
            workspace_id=workspace_id, resolution=resolution,
        )
    except ValueError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc)) from exc
    await db.commit()
    return {"resolved": True, **result}


@router.post("/knowledge/pages/{page_id}/publish")
async def publish_knowledge_page(
    http_request: Request,
    page_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Promote a reviewed page revision and its dependent claims/edges.

    Publishing is intentionally explicit so deployments can disable automatic
    compiler promotion while retaining the same query contract.
    """
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(http_request, user_id=current_user.id)
    )
    page = await db.scalar(
        select(KnowledgePage).where(
            KnowledgePage.id == page_id,
            KnowledgePage.owner_id == current_user.id,
            KnowledgePage.tenant_id == tenant_id,
            KnowledgePage.workspace_id == workspace_id,
        )
    )
    if page is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Knowledge page not found")

    version = await db.get(KnowledgeSourceVersion, page.source_version_id)
    if version is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Knowledge revision not found")
    source = await db.get(KnowledgeSource, version.source_id)
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Knowledge source not found")

    pages = (
        await db.execute(
            select(KnowledgePage).where(
                KnowledgePage.source_version_id == version.id,
                KnowledgePage.owner_id == current_user.id,
            )
        )
    ).scalars().all()
    claims = (
        await db.execute(
            select(KnowledgeClaim).where(
                KnowledgeClaim.source_version_id == version.id,
                KnowledgeClaim.owner_id == current_user.id,
            )
        )
    ).scalars().all()
    relations = (
        await db.execute(
            select(KnowledgeRelation).where(
                KnowledgeRelation.source_version_id == version.id,
                KnowledgeRelation.owner_id == current_user.id,
            )
        )
    ).scalars().all()

    previous_version_id = source.active_version_id
    if previous_version_id and previous_version_id != version.id:
        previous = await db.get(KnowledgeSourceVersion, previous_version_id)
        if previous is not None:
            previous.status = KnowledgeStatus.ARCHIVED.value
            for model in (KnowledgePage, KnowledgeClaim, KnowledgeRelation):
                await db.execute(
                    update(model)
                    .where(model.source_version_id == previous.id)
                    .values(status=KnowledgeStatus.ARCHIVED.value)
                )
    for item in (*pages, *claims, *relations):
        item.status = KnowledgeStatus.PUBLISHED.value
    version.status = KnowledgeStatus.PUBLISHED.value
    version.compiled_at = version.compiled_at or datetime.now(timezone.utc)
    source.active_version_id = version.id
    source.status = KnowledgeStatus.PUBLISHED.value
    await db.commit()
    return {
        "published": True,
        "page_id": page_id,
        "source_id": source.id,
        "source_version_id": version.id,
    }


@router.get("/knowledge/lint/issues")
async def list_lint_issues(
    http_request: Request,
    status: str = "open",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    rows = (
        await db.execute(
            select(KnowledgeLintIssue)
            .where(
                KnowledgeLintIssue.tenant_id == tenant_id,
                KnowledgeLintIssue.workspace_id == workspace_id,
                KnowledgeLintIssue.owner_id == current_user.id,
                KnowledgeLintIssue.status == status,
            )
            .order_by(KnowledgeLintIssue.detected_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": issue.id,
            "severity": issue.severity,
            "code": issue.code,
            "resource_type": issue.resource_type,
            "resource_id": issue.resource_id,
            "message": issue.message,
            "status": issue.status,
            "details": issue.details,
        }
        for issue in rows
    ]


@router.post("/knowledge/feedback")
async def submit_knowledge_feedback(
    http_request: Request,
    req: KnowledgeFeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(http_request, user_id=current_user.id))
    target_models = {
        "knowledge_page": KnowledgePage,
        "knowledge_claim": KnowledgeClaim,
        "knowledge_source": KnowledgeSource,
    }
    model = target_models.get(req.target_type)
    if model is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Unsupported knowledge feedback target")
    target = await db.get(model, req.target_id)
    if (
        target is None
        or getattr(target, "tenant_id", None) != tenant_id
        or getattr(target, "workspace_id", None) != workspace_id
        or getattr(target, "owner_id", None) != current_user.id
    ):
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Knowledge target not found")
    db.add(
        KnowledgeFeedback(
            id=str(uuid.uuid4()),
            session_id=req.session_id,
            user_id=current_user.id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            target_type=req.target_type,
            target_id=req.target_id,
            feedback_type=req.feedback_type,
            score=req.score,
            correction=req.correction,
            feedback_metadata={"source": "knowledge_api"},
        )
    )
    await db.commit()
    return {"accepted": True, "target_type": req.target_type, "target_id": req.target_id}
