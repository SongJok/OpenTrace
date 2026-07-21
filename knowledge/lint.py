"""Knowledge health checks and persistent Lint issue synchronization."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.config.settings import settings
from infra.storage.models import (
    DocumentChunk,
    KnowledgeClaim,
    KnowledgeLintIssue,
    KnowledgeMergeCase,
    KnowledgePage,
    KnowledgeRelation,
    KnowledgeSource,
)
from knowledge.evolution import record_observation


def _issue_key(code: str, resource_type: str, resource_id: str) -> str:
    return hashlib.sha256(f"{code}:{resource_type}:{resource_id}".encode("utf-8")).hexdigest()[:48]


async def run_knowledge_lint(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    owner_id: str | None = None,
) -> dict[str, Any]:
    page_conditions = [KnowledgePage.tenant_id == tenant_id, KnowledgePage.workspace_id == workspace_id]
    claim_conditions = [KnowledgeClaim.tenant_id == tenant_id, KnowledgeClaim.workspace_id == workspace_id]
    relation_conditions = [KnowledgeRelation.tenant_id == tenant_id, KnowledgeRelation.workspace_id == workspace_id]
    source_conditions = [KnowledgeSource.tenant_id == tenant_id, KnowledgeSource.workspace_id == workspace_id]
    issue_conditions = [KnowledgeLintIssue.tenant_id == tenant_id, KnowledgeLintIssue.workspace_id == workspace_id]
    if owner_id:
        page_conditions.append(KnowledgePage.owner_id == owner_id)
        claim_conditions.append(KnowledgeClaim.owner_id == owner_id)
        relation_conditions.append(KnowledgeRelation.owner_id == owner_id)
        source_conditions.append(KnowledgeSource.owner_id == owner_id)
        issue_conditions.append(KnowledgeLintIssue.owner_id == owner_id)
    pages = list((await db.execute(select(KnowledgePage).where(*page_conditions))).scalars().all())
    claims = list((await db.execute(select(KnowledgeClaim).where(*claim_conditions))).scalars().all())
    relations = list((await db.execute(select(KnowledgeRelation).where(*relation_conditions))).scalars().all())
    sources = list((await db.execute(select(KnowledgeSource).where(*source_conditions))).scalars().all())
    chunk_ids = {row[0] for row in (await db.execute(select(DocumentChunk.id))).all()}
    chunk_lengths = {
        row[0]: len(row[1] or "")
        for row in (await db.execute(select(DocumentChunk.id, DocumentChunk.content))).all()
    }
    relation_targets = {r.target_page_id for r in relations if r.status == "published"}
    claims_by_page: set[str] = {claim.page_id for claim in claims if claim.status == "published"}
    duplicate_groups: dict[str, list[KnowledgeClaim]] = {}
    active_version_ids = {source.active_version_id for source in sources if source.active_version_id}
    for claim in claims:
        if (
            claim.status == "published"
            and claim.source_version_id in active_version_ids
            and claim.normalized_text
        ):
            duplicate_groups.setdefault(claim.normalized_text, []).append(claim)
    findings: list[dict[str, Any]] = []
    for page in pages:
        if page.status == "published" and page.page_type != "overview" and page.id not in claims_by_page:
            findings.append({
                "code": "page_without_claims",
                "severity": "warning",
                "resource_type": "knowledge_page",
                "resource_id": page.id,
                "message": "Published page has no traceable claims.",
            })
        if page.status == "published" and page.page_type != "overview" and page.id not in relation_targets:
            findings.append({
                "code": "orphan_page",
                "severity": "warning",
                "resource_type": "knowledge_page",
                "resource_id": page.id,
                "message": "Published page is not linked from the knowledge graph.",
            })
    for claim in claims:
        if claim.status == "published" and not claim.evidence_chunk_id:
            findings.append({
                "code": "claim_without_evidence",
                "severity": "error",
                "resource_type": "knowledge_claim",
                "resource_id": claim.id,
                "message": "Published claim has no evidence chunk provenance.",
            })
        if claim.status == "published" and claim.evidence_chunk_id:
            if claim.evidence_chunk_id not in chunk_ids:
                findings.append({
                    "code": "claim_evidence_chunk_missing",
                    "severity": "error",
                    "resource_type": "knowledge_claim",
                    "resource_id": claim.id,
                    "message": "Claim evidence chunk no longer exists.",
                })
            else:
                length = chunk_lengths[claim.evidence_chunk_id]
                start = claim.evidence_start or 0
                end = claim.evidence_end if claim.evidence_end is not None else length
                if start < 0 or end < start or end > length:
                    findings.append({
                        "code": "claim_evidence_span_invalid",
                        "severity": "error",
                        "resource_type": "knowledge_claim",
                        "resource_id": claim.id,
                        "message": "Claim evidence span falls outside its source chunk.",
                    })
    for entity_key, grouped in duplicate_groups.items():
        candidate_ids = [claim.id for claim in grouped]
        if len(candidate_ids) < 2:
            continue
        existing_case = await db.scalar(select(KnowledgeMergeCase).where(
            KnowledgeMergeCase.tenant_id == tenant_id,
            KnowledgeMergeCase.workspace_id == workspace_id,
            KnowledgeMergeCase.owner_id == owner_id,
            KnowledgeMergeCase.entity_key == entity_key,
            KnowledgeMergeCase.status == "open",
        ))
        if existing_case is None:
            db.add(KnowledgeMergeCase(
                id=str(uuid.uuid4()), owner_id=owner_id, tenant_id=tenant_id, workspace_id=workspace_id,
                entity_key=entity_key, conflict_type="duplicate_claim", candidate_ids=candidate_ids,
                resolution={},
            ))
        findings.append({
            "code": "duplicate_claim_requires_merge",
            "severity": "warning",
            "resource_type": "knowledge_merge_case",
            "resource_id": entity_key,
            "message": "Multiple published claims share the same normalized text and require review.",
        })
    for source in sources:
        if source.status == "published" and not source.active_version_id:
            findings.append({
                "code": "published_source_without_active_version",
                "severity": "error",
                "resource_type": "knowledge_source",
                "resource_id": source.id,
                "message": "Published source has no active compiled version.",
            })
        if source.status == "published" and source.updated_at:
            updated_at = source.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, settings.knowledge_stale_after_days))
            if updated_at < cutoff:
                findings.append({
                    "code": "source_stale",
                    "severity": "warning",
                    "resource_type": "knowledge_source",
                    "resource_id": source.id,
                    "message": f"Published source has not changed for {settings.knowledge_stale_after_days} days.",
                })

    current_keys = set()
    for finding in findings:
        key = _issue_key(finding["code"], finding["resource_type"], finding["resource_id"])
        current_keys.add(key)
        existing = await db.scalar(
            select(KnowledgeLintIssue).where(
                KnowledgeLintIssue.tenant_id == tenant_id,
                KnowledgeLintIssue.workspace_id == workspace_id,
                KnowledgeLintIssue.issue_key == key,
                KnowledgeLintIssue.owner_id == owner_id,
            )
        )
        if existing is None:
            db.add(
                KnowledgeLintIssue(
                    issue_key=key,
                    owner_id=owner_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    severity=finding["severity"],
                    code=finding["code"],
                    resource_type=finding["resource_type"],
                    resource_id=finding["resource_id"],
                    message=finding["message"],
                    details={},
                )
            )
        else:
            existing.status = "open"
            existing.resolved_at = None
            existing.message = finding["message"]
            existing.severity = finding["severity"]

    existing_issues = list(
        (
            await db.execute(
                select(KnowledgeLintIssue).where(*issue_conditions, KnowledgeLintIssue.status == "open")
            )
        ).scalars().all()
    )
    for issue in existing_issues:
        if issue.issue_key not in current_keys:
            issue.status = "resolved"
            issue.resolved_at = datetime.now(timezone.utc)
    await record_observation(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        owner_id=owner_id,
        metric="open_lint_issues",
        value=float(len(findings)),
        dimensions={"finding_codes": sorted({item["code"] for item in findings})},
        trigger="lint",
    )
    return {"findings": findings, "open_count": len(findings)}
