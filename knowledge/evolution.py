"""Metacognitive observations and human-approved evolution proposals."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import KnowledgeFeedback, KnowledgeLintIssue, KnowledgeObservation, KnowledgeRule


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
    corrections = await db.scalar(
        select(func.count(KnowledgeFeedback.id)).where(
            KnowledgeFeedback.tenant_id == tenant_id,
            KnowledgeFeedback.workspace_id == workspace_id,
            KnowledgeFeedback.user_id == owner_id,
            KnowledgeFeedback.correction.is_not(None),
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
        metric="feedback_corrections",
        value=float(corrections),
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
    if corrections:
        recommendations.append("replay_corrected_traces_before_rule_approval")
    proposed_schema = {
        "required_page_fields": ["title", "content", "page_type"],
        "required_claim_fields": ["text", "evidence_chunk_id"],
        "required_relation_fields": ["source_page_id", "target_page_id", "relation_type"],
        "quality_gates": {
            "max_open_lint_issues": int(issue_count),
            "negative_feedback_count": int(negative_feedback),
            "correction_count": int(corrections),
        },
    }
    # A proposal is a persisted draft rule.  It is never selected by the
    # compiler until a human explicitly approves it through the rule API.
    proposal_rule = await db.scalar(select(KnowledgeRule).where(
        KnowledgeRule.owner_id == owner_id,
        KnowledgeRule.tenant_id == tenant_id,
        KnowledgeRule.workspace_id == workspace_id,
        KnowledgeRule.rule_key == "knowledge_compiler",
        KnowledgeRule.status == "draft",
        KnowledgeRule.rule_type == "evolution_proposal",
    ).order_by(KnowledgeRule.version.desc()))
    if proposal_rule is None:
        latest = await db.scalar(select(KnowledgeRule).where(
            KnowledgeRule.owner_id == owner_id,
            KnowledgeRule.tenant_id == tenant_id,
            KnowledgeRule.workspace_id == workspace_id,
            KnowledgeRule.rule_key == "knowledge_compiler",
        ).order_by(KnowledgeRule.version.desc()))
        proposal_rule = KnowledgeRule(
            id=str(uuid.uuid4()), owner_id=owner_id, tenant_id=tenant_id, workspace_id=workspace_id,
            rule_key="knowledge_compiler", version=(latest.version + 1 if latest else 1),
            rule_type="evolution_proposal", status="draft", schema_json=proposed_schema,
            instructions="由质量信号生成；必须经过离线回放和人工批准后才能生效。",
            provenance={"signals": {"open_lint_issues": int(issue_count), "negative_feedback": int(negative_feedback), "corrections": int(corrections)}, "requires_human_approval": True},
            created_by=owner_id,
        )
        db.add(proposal_rule)
        await db.flush()
    return {
        "status": "proposal",
        "signals": {"open_lint_issues": int(issue_count), "negative_feedback": int(negative_feedback)},
        "recommendations": recommendations,
        "requires_human_approval": True,
        "proposal": {
            "rule_id": proposal_rule.id,
            "rule_key": proposal_rule.rule_key,
            "version": proposal_rule.version,
            "status": proposal_rule.status,
            "schema": proposal_rule.schema_json,
        },
    }
