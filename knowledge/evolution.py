"""Metacognitive observations and human-approved evolution proposals."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import KnowledgeFeedback, KnowledgeLintIssue, KnowledgeObservation


async def record_observation(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    owner_id: str | None,
    metric: str,
    value: float,
    dimensions: dict[str, Any] | None = None,
    trigger: str = "scheduled",
) -> KnowledgeObservation:
    row = KnowledgeObservation(
        id=str(uuid.uuid4()),
        owner_id=owner_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        metric=metric,
        value=float(value),
        dimensions=dimensions or {},
        trigger=trigger,
    )
    db.add(row)
    await db.flush()
    return row


async def build_evolution_proposal(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    owner_id: str | None,
) -> dict[str, Any]:
    """Summarize observed quality signals without silently changing rules."""
    issue_count = await db.scalar(
        select(func.count(KnowledgeLintIssue.id)).where(
            KnowledgeLintIssue.tenant_id == tenant_id,
            KnowledgeLintIssue.workspace_id == workspace_id,
            KnowledgeLintIssue.owner_id == owner_id,
            KnowledgeLintIssue.status == "open",
        )
    ) or 0
    negative_feedback = await db.scalar(
        select(func.count(KnowledgeFeedback.id)).where(
            KnowledgeFeedback.tenant_id == tenant_id,
            KnowledgeFeedback.workspace_id == workspace_id,
            KnowledgeFeedback.user_id == owner_id,
            KnowledgeFeedback.feedback_type.in_(["negative", "incorrect", "correction"]),
        )
    ) or 0
    await record_observation(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        owner_id=owner_id,
        metric="open_lint_issues",
        value=float(issue_count),
        trigger="evolution_review",
    )
    await record_observation(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        owner_id=owner_id,
        metric="negative_feedback",
        value=float(negative_feedback),
        trigger="evolution_review",
    )
    recommendations = []
    if issue_count:
        recommendations.append("review_lint_findings_before_promoting_new_rule")
    if negative_feedback:
        recommendations.append("promote_feedback_corrections_to_rule_review")
    return {
        "status": "proposal",
        "signals": {"open_lint_issues": int(issue_count), "negative_feedback": int(negative_feedback)},
        "recommendations": recommendations,
        "requires_human_approval": True,
    }
