"""Human-approved claim merge application; conflicts never merge silently."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import KnowledgeClaim, KnowledgeMergeCase
from knowledge.compiler import content_hash


async def resolve_merge_case(
    db: AsyncSession,
    *,
    case_id: str,
    owner_id: str | None,
    tenant_id: str,
    workspace_id: str,
    resolution: dict[str, Any],
    resolved_by: str | None = None,
    allowed_claim_ids: set[str] | None = None,
) -> dict[str, Any]:
    conditions = [
        KnowledgeMergeCase.id == case_id,
        KnowledgeMergeCase.tenant_id == tenant_id,
        KnowledgeMergeCase.workspace_id == workspace_id,
    ]
    if owner_id is not None:
        conditions.append(KnowledgeMergeCase.owner_id == owner_id)
    case = await db.scalar(select(KnowledgeMergeCase).where(*conditions))
    if case is None:
        raise ValueError("knowledge_merge_case_not_found")
    if case.status != "open":
        raise ValueError("knowledge_merge_case_already_resolved")
    action = str(resolution.get("action") or "merge")
    candidate_ids = [str(item) for item in (case.candidate_ids or [])]
    if allowed_claim_ids is not None and not set(candidate_ids).issubset(allowed_claim_ids):
        raise ValueError("knowledge_merge_case_outside_governance_scope")
    actor_id = resolved_by or owner_id
    if not actor_id:
        raise ValueError("knowledge_merge_case_resolver_required")
    if action in {"reject", "keep_separate"}:
        case.status = "rejected"
        case.resolution = {**resolution, "resolved_via": "human_review"}
        case.resolved_by = actor_id
        case.resolved_at = datetime.now(UTC)
        await db.flush()
        return {"case_id": case.id, "status": case.status, "applied_claim_ids": []}

    keep_id = str(resolution.get("keep_claim_id") or "")
    if keep_id not in candidate_ids:
        raise ValueError("merge_resolution_requires_valid_keep_claim_id")
    claim_conditions = [
        KnowledgeClaim.id.in_(candidate_ids),
        KnowledgeClaim.tenant_id == tenant_id,
        KnowledgeClaim.workspace_id == workspace_id,
    ]
    if owner_id is not None and allowed_claim_ids is None:
        claim_conditions.append(KnowledgeClaim.owner_id == owner_id)
    claims = list((await db.execute(select(KnowledgeClaim).where(*claim_conditions))).scalars())
    by_id = {claim.id: claim for claim in claims}
    if set(by_id) != set(candidate_ids):
        raise ValueError("merge_candidate_claim_not_found")
    kept = by_id[keep_id]
    merged_text = str(resolution.get("merged_text") or "").strip()
    if merged_text:
        kept.text = merged_text[:1500]
        kept.normalized_text = merged_text.lower()[:1500]
        kept.claim_hash = content_hash(kept.normalized_text)
    kept.claim_metadata = {
        **(kept.claim_metadata or {}),
        "merge_case_id": case.id,
        "merged_candidate_ids": candidate_ids,
        "merge_resolution": resolution,
    }
    archived: list[str] = []
    for claim in claims:
        if claim.id == keep_id:
            claim.status = "published"
            continue
        claim.status = "archived"
        claim.claim_metadata = {
            **(claim.claim_metadata or {}),
            "merged_into_claim_id": keep_id,
        }
        archived.append(claim.id)
    case.status = "resolved"
    case.resolution = {**resolution, "resolved_via": "human_review", "kept_claim_id": keep_id}
    case.resolved_by = actor_id
    case.resolved_at = datetime.now(UTC)
    await db.flush()
    return {
        "case_id": case.id,
        "status": case.status,
        "kept_claim_id": keep_id,
        "archived_claim_ids": archived,
    }
