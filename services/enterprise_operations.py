"""管理员企业运营中心的 PostgreSQL 聚合投影。"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import (
    AlertEvent,
    AlertRule,
    DataSource,
    EnterpriseDirectoryMembership,
    EnterpriseDirectoryPrincipal,
    EnterpriseDirectorySyncRun,
    GoalRun,
    KnowledgeFeedback,
    KnowledgeReviewTask,
    KnowledgeSource,
    KnowledgeSpace,
    ResponseApproval,
    ResponseModelCall,
    ResponseRecord,
    TaskDefinition,
)


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return int(ordered[index])


async def enterprise_operations_overview(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
) -> dict[str, Any]:
    """聚合当前租户工作区的采用、质量、治理和资产指标。"""

    now = datetime.now(UTC)
    since_24h = now - timedelta(hours=24)
    since_30d = now - timedelta(days=30)
    response_scope = (
        ResponseRecord.tenant_id == tenant_id,
        ResponseRecord.workspace_id == workspace_id,
    )
    responses_24h = list(
        (
            await db.execute(
                select(ResponseRecord).where(
                    *response_scope,
                    ResponseRecord.created_at >= since_24h,
                )
            )
        ).scalars()
    )
    active_users_30d = int(
        await db.scalar(
            select(func.count(distinct(ResponseRecord.user_id))).where(
                *response_scope,
                ResponseRecord.created_at >= since_30d,
            )
        )
        or 0
    )
    response_ids = [row.id for row in responses_24h]
    model_calls: list[ResponseModelCall] = []
    if response_ids:
        model_calls = list(
            (
                await db.execute(
                    select(ResponseModelCall).where(ResponseModelCall.response_id.in_(response_ids))
                )
            ).scalars()
        )
    pending_approvals = int(
        await db.scalar(
            select(func.count(ResponseApproval.id))
            .join(ResponseRecord, ResponseApproval.response_id == ResponseRecord.id)
            .where(
                *response_scope,
                ResponseApproval.status == "pending",
            )
        )
        or 0
    )

    goals = list(
        (
            await db.execute(
                select(GoalRun).where(
                    GoalRun.tenant_id == tenant_id,
                    GoalRun.workspace_id == workspace_id,
                )
            )
        ).scalars()
    )
    scheduled_tasks = int(
        await db.scalar(
            select(func.count(TaskDefinition.id)).where(
                TaskDefinition.tenant_id == tenant_id,
                TaskDefinition.workspace_id == workspace_id,
                TaskDefinition.status == "active",
            )
        )
        or 0
    )
    alert_rules = list(
        (
            await db.execute(
                select(AlertRule).where(
                    AlertRule.tenant_id == tenant_id,
                    AlertRule.workspace_id == workspace_id,
                )
            )
        ).scalars()
    )
    alert_ids = [row.id for row in alert_rules]
    unacknowledged_alerts: list[AlertEvent] = []
    if alert_ids:
        unacknowledged_alerts = list(
            (
                await db.execute(
                    select(AlertEvent).where(
                        AlertEvent.rule_id.in_(alert_ids),
                        AlertEvent.state == "triggered",
                        AlertEvent.acknowledged_at.is_(None),
                    )
                )
            ).scalars()
        )

    data_sources = list(
        (
            await db.execute(
                select(DataSource).where(
                    DataSource.tenant_id == tenant_id,
                    DataSource.workspace_id == workspace_id,
                )
            )
        ).scalars()
    )
    knowledge_spaces = int(
        await db.scalar(
            select(func.count(KnowledgeSpace.id)).where(
                KnowledgeSpace.tenant_id == tenant_id,
                KnowledgeSpace.workspace_id == workspace_id,
                KnowledgeSpace.status == "active",
            )
        )
        or 0
    )
    knowledge_sources = list(
        (
            await db.execute(
                select(KnowledgeSource).where(
                    KnowledgeSource.tenant_id == tenant_id,
                    KnowledgeSource.workspace_id == workspace_id,
                    KnowledgeSource.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    pending_reviews = int(
        await db.scalar(
            select(func.count(KnowledgeReviewTask.id)).where(
                KnowledgeReviewTask.tenant_id == tenant_id,
                KnowledgeReviewTask.workspace_id == workspace_id,
                KnowledgeReviewTask.status == "pending",
            )
        )
        or 0
    )
    unresolved_feedback = int(
        await db.scalar(
            select(func.count(KnowledgeFeedback.id)).where(
                KnowledgeFeedback.tenant_id == tenant_id,
                KnowledgeFeedback.workspace_id == workspace_id,
                KnowledgeFeedback.applied.is_(False),
            )
        )
        or 0
    )
    directory_principals = int(
        await db.scalar(
            select(func.count(EnterpriseDirectoryPrincipal.id)).where(
                EnterpriseDirectoryPrincipal.tenant_id == tenant_id,
                EnterpriseDirectoryPrincipal.workspace_id == workspace_id,
                EnterpriseDirectoryPrincipal.status == "active",
            )
        )
        or 0
    )
    directory_memberships = int(
        await db.scalar(
            select(func.count(EnterpriseDirectoryMembership.id)).where(
                EnterpriseDirectoryMembership.tenant_id == tenant_id,
                EnterpriseDirectoryMembership.workspace_id == workspace_id,
                EnterpriseDirectoryMembership.status == "active",
            )
        )
        or 0
    )
    last_directory_sync = await db.scalar(
        select(EnterpriseDirectorySyncRun)
        .where(
            EnterpriseDirectorySyncRun.tenant_id == tenant_id,
            EnterpriseDirectorySyncRun.workspace_id == workspace_id,
        )
        .order_by(EnterpriseDirectorySyncRun.created_at.desc())
        .limit(1)
    )

    completed = sum(row.status == "completed" for row in responses_24h)
    failed = sum(row.status in {"failed", "incomplete"} for row in responses_24h)
    cancelled = sum(row.status == "cancelled" for row in responses_24h)
    active = sum(row.status in {"queued", "in_progress"} for row in responses_24h)
    requires_action = sum(row.status == "requires_action" for row in responses_24h)
    total = len(responses_24h)
    terminal = completed + failed + cancelled
    success_rate = round(completed / terminal * 100, 1) if terminal else 100.0
    latencies = [int(row.latency_ms) for row in model_calls if row.latency_ms is not None]
    prompt_tokens = 0
    completion_tokens = 0
    model_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "latencies": []}
    )
    for call in model_calls:
        metadata = dict(call.call_metadata or {})
        prompt = int(metadata.get("prompt_tokens") or 0)
        completion = int(metadata.get("completion_tokens") or 0)
        prompt_tokens += prompt
        completion_tokens += completion
        bucket = model_stats[str(call.model or "unknown")]
        bucket["calls"] += 1
        bucket["prompt_tokens"] += prompt
        bucket["completion_tokens"] += completion
        if call.latency_ms is not None:
            bucket["latencies"].append(int(call.latency_ms))
    model_usage = [
        {
            "model": model,
            "calls": values["calls"],
            "prompt_tokens": values["prompt_tokens"],
            "completion_tokens": values["completion_tokens"],
            "avg_latency_ms": (
                round(sum(values["latencies"]) / len(values["latencies"]))
                if values["latencies"]
                else 0
            ),
        }
        for model, values in model_stats.items()
    ]
    model_usage.sort(key=lambda item: item["calls"], reverse=True)

    due_reviews = sum(
        row.status == "published" and row.review_due_at is not None and row.review_due_at <= now
        for row in knowledge_sources
    )
    stale_knowledge = sum(
        row.sync_status in {"stale", "error", "failed"} for row in knowledge_sources
    )
    critical_alerts = sum(row.severity == "critical" for row in unacknowledged_alerts)
    active_goals = sum(row.status in {"queued", "in_progress", "requires_action"} for row in goals)
    completed_goals = sum(row.status == "completed" for row in goals)
    reliability_score = max(0, round(success_rate - min(30, failed * 3)))
    governance_score = max(
        0,
        100
        - min(
            100,
            pending_approvals * 4
            + critical_alerts * 10
            + pending_reviews * 2
            + unresolved_feedback * 3,
        ),
    )
    knowledge_score = max(0, 100 - min(100, due_reviews * 5 + stale_knowledge * 6))
    adoption_score = min(
        100,
        active_users_30d * 10
        + min(30, active_goals * 5 + scheduled_tasks * 5)
        + (20 if any(row.status == "active" for row in data_sources) else 0)
        + (20 if any(row.status == "published" for row in knowledge_sources) else 0),
    )
    health_score = round(
        reliability_score * 0.35
        + governance_score * 0.30
        + knowledge_score * 0.20
        + adoption_score * 0.15
    )
    health_status = (
        "healthy" if health_score >= 85 else "attention" if health_score >= 60 else "critical"
    )

    risks: list[dict[str, Any]] = []
    for code, severity, count, title, route in (
        ("response_failures", "error", failed, "过去 24 小时失败执行", "/chat"),
        ("pending_approvals", "warning", pending_approvals, "待处理工具审批", "/work"),
        ("critical_alerts", "critical", critical_alerts, "未确认关键预警", "/alerts"),
        (
            "knowledge_reviews",
            "warning",
            due_reviews + pending_reviews,
            "知识复审积压",
            "/knowledge",
        ),
        ("knowledge_feedback", "warning", unresolved_feedback, "未处理知识反馈", "/knowledge"),
    ):
        if count:
            risks.append(
                {
                    "code": code,
                    "severity": severity,
                    "count": count,
                    "title": title,
                    "route": route,
                }
            )

    return {
        "generated_at": now.isoformat(),
        "scope": {"tenant_id": tenant_id, "workspace_id": workspace_id},
        "health": {
            "score": health_score,
            "status": health_status,
            "dimensions": {
                "reliability": reliability_score,
                "governance": governance_score,
                "knowledge": knowledge_score,
                "adoption": adoption_score,
            },
        },
        "adoption": {
            "active_users_30d": active_users_30d,
            "active_goals": active_goals,
            "completed_goals": completed_goals,
            "scheduled_tasks": scheduled_tasks,
            "active_alerts": sum(row.status == "active" for row in alert_rules),
        },
        "responses": {
            "total_24h": total,
            "completed_24h": completed,
            "failed_24h": failed,
            "requires_action_24h": requires_action,
            "active_24h": active,
            "success_rate": success_rate,
            "pending_approvals": pending_approvals,
            "model_calls_24h": len(model_calls),
            "prompt_tokens_24h": prompt_tokens,
            "completion_tokens_24h": completion_tokens,
            "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
            "p95_latency_ms": _percentile(latencies, 0.95),
        },
        "assets": {
            "data_sources": len(data_sources),
            "active_data_sources": sum(row.status == "active" for row in data_sources),
            "knowledge_spaces": knowledge_spaces,
            "knowledge_sources": len(knowledge_sources),
            "published_knowledge": sum(row.status == "published" for row in knowledge_sources),
            "due_reviews": due_reviews,
            "stale_knowledge": stale_knowledge,
            "pending_reviews": pending_reviews,
            "unresolved_feedback": unresolved_feedback,
        },
        "directory": {
            "principals": directory_principals,
            "memberships": directory_memberships,
            "last_sync": (
                {
                    "id": last_directory_sync.id,
                    "provider": last_directory_sync.provider,
                    "status": last_directory_sync.status,
                    "completed_at": (
                        last_directory_sync.completed_at.isoformat()
                        if last_directory_sync.completed_at
                        else None
                    ),
                    "stats": dict(last_directory_sync.stats or {}),
                }
                if last_directory_sync
                else None
            ),
        },
        "alerts": {
            "unacknowledged": len(unacknowledged_alerts),
            "critical": critical_alerts,
        },
        "model_usage": model_usage[:10],
        "risks": risks,
    }
