from __future__ import annotations

import asyncio
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from agents.base import TaskMessage
from agents.data_agent import DataAgent
from infra.config.settings import settings
from infra.observability.logger import get_logger
from infra.responses.scheduler import next_occurrence
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import AlertEvent, AlertRule, DataSource, Project, TaskNotification

logger = get_logger(__name__)


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def extract_alert_value(rows: list[dict[str, Any]], metric_column: str | None, aggregation: str) -> float | None:
    if aggregation == "count":
        return float(len(rows))
    values: list[float] = []
    for row in rows:
        if metric_column:
            value = _numeric(row.get(metric_column))
        else:
            value = next((_numeric(item) for item in row.values() if _numeric(item) is not None), None)
        if value is not None:
            values.append(value)
    if not values:
        return None
    if aggregation == "sum":
        return sum(values)
    if aggregation == "avg":
        return sum(values) / len(values)
    if aggregation == "min":
        return min(values)
    if aggregation == "max":
        return max(values)
    return values[0]


def evaluate_condition(operator: str, value: float, threshold: float, previous: float | None) -> tuple[bool, float]:
    evaluated = value
    if operator in {"change_pct_gt", "change_pct_lt"}:
        if previous is None or previous == 0:
            return False, 0.0
        evaluated = ((value - previous) / abs(previous)) * 100.0
    operations = {
        "gt": evaluated > threshold,
        "gte": evaluated >= threshold,
        "lt": evaluated < threshold,
        "lte": evaluated <= threshold,
        "eq": evaluated == threshold,
        "neq": evaluated != threshold,
        "change_pct_gt": evaluated > threshold,
        "change_pct_lt": evaluated < threshold,
    }
    return bool(operations.get(operator, False)), evaluated


async def claim_due_alerts(*, limit: int = 10) -> list[str]:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        rules = list(
            (
                await db.execute(
                    select(AlertRule)
                    .where(
                        AlertRule.status == "active",
                        AlertRule.next_run_at.is_not(None),
                        AlertRule.next_run_at <= now,
                    )
                    .order_by(AlertRule.next_run_at)
                    .with_for_update(skip_locked=True)
                    .limit(max(1, min(limit, 50)))
                )
            ).scalars().all()
        )
        for rule in rules:
            scheduled_for = rule.next_run_at or now
            rule.last_run_at = now
            rule.next_run_at = next_occurrence(rule.rrule, rule.timezone, after=scheduled_for)
        await db.commit()
        return [rule.id for rule in rules]


async def evaluate_alert_rule(rule_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        rule = await db.get(AlertRule, rule_id)
        if rule is None or rule.status != "active":
            return {"status": "skipped", "rule_id": rule_id}
        source = await db.scalar(
            select(DataSource).where(
                DataSource.id == rule.data_source_id,
                DataSource.user_id == rule.user_id,
                DataSource.tenant_id == rule.tenant_id,
                DataSource.workspace_id == rule.workspace_id,
                DataSource.status == "active",
            )
        )
        if source is None:
            rule.last_error = "data_source_not_authorized"
            await db.commit()
            return {"status": "error", "rule_id": rule_id, "error": rule.last_error}
        if rule.project_id:
            project = await db.scalar(
                select(Project).where(
                    Project.id == rule.project_id,
                    Project.user_id == rule.user_id,
                    Project.tenant_id == rule.tenant_id,
                    Project.workspace_id == rule.workspace_id,
                    Project.archived_at.is_(None),
                )
            )
            if project is None or rule.data_source_id not in set(project.data_source_ids or []):
                rule.last_error = "project_data_source_not_authorized"
                await db.commit()
                return {"status": "error", "rule_id": rule_id, "error": rule.last_error}
        snapshot = {
            "question": rule.question,
            "data_source_id": rule.data_source_id,
            "user_id": rule.user_id,
            "project_id": rule.project_id,
        }

    result = await DataAgent().execute(
        TaskMessage(
            task_id=f"alert:{rule_id}:{uuid.uuid4().hex[:10]}",
            agent_type="data",
            query=snapshot["question"],
            user_id=snapshot["user_id"],
            params={
                "data_source_id": snapshot["data_source_id"],
                "project_id": snapshot["project_id"],
                "alert_mode": True,
            },
        )
    )

    async with AsyncSessionLocal() as db:
        rule = await db.get(AlertRule, rule_id, with_for_update=True)
        if rule is None:
            return {"status": "skipped", "rule_id": rule_id}
        if result.status != "success":
            rule.last_error = str(result.error or result.content or "data_query_failed")[:2000]
            await db.commit()
            return {"status": "error", "rule_id": rule_id, "error": rule.last_error}

        rows = (result.metadata or {}).get("rows") or []
        rows = rows if isinstance(rows, list) else []
        value = extract_alert_value(rows, rule.metric_column, rule.aggregation)
        if value is None:
            rule.last_error = "alert_metric_value_not_found"
            await db.commit()
            return {"status": "error", "rule_id": rule_id, "error": rule.last_error}

        previous_value = rule.last_value
        triggered, evaluated_value = evaluate_condition(rule.operator, value, rule.threshold, previous_value)
        previous_state = rule.last_state
        next_state = "triggered" if triggered else "normal"
        now = datetime.now(UTC)
        cooldown_elapsed = (
            rule.last_triggered_at is None
            or now >= rule.last_triggered_at + timedelta(seconds=max(0, rule.cooldown_seconds))
        )
        should_emit = (triggered and (previous_state != "triggered" or cooldown_elapsed)) or (
            not triggered and previous_state == "triggered"
        )
        rule.last_value = value
        rule.last_state = next_state
        rule.last_error = None
        event = None
        if should_emit:
            event_state = "triggered" if triggered else "resolved"
            summary = (
                f"{rule.name}：当前值 {evaluated_value:.4g}，条件 {rule.operator} {rule.threshold:.4g}"
                if triggered
                else f"{rule.name} 已恢复：当前值 {evaluated_value:.4g}"
            )
            event = AlertEvent(
                id=str(uuid.uuid4()),
                rule_id=rule.id,
                user_id=rule.user_id,
                state=event_state,
                severity=rule.severity if triggered else "info",
                value=evaluated_value,
                threshold=rule.threshold,
                summary=summary,
                evidence={
                    "raw_value": value,
                    "previous_value": previous_value,
                    "operator": rule.operator,
                    "metric_column": rule.metric_column,
                    "aggregation": rule.aggregation,
                    "sql": (result.metadata or {}).get("sql"),
                    "rows_preview": rows[:5],
                    "confidence": result.confidence,
                },
            )
            db.add(event)
            db.add(
                TaskNotification(
                    id=str(uuid.uuid4()),
                    user_id=rule.user_id,
                    task_id=rule.id,
                    run_id=event.id,
                    level=event.severity,
                    title=rule.name,
                    body=summary,
                )
            )
            if triggered:
                rule.last_triggered_at = now
        await db.commit()
        return {
            "status": "triggered" if triggered else "normal",
            "rule_id": rule_id,
            "value": value,
            "event_id": event.id if event else None,
        }


async def process_due_alerts(*, limit: int = 10) -> int:
    rule_ids = await claim_due_alerts(limit=limit)
    if rule_ids:
        await asyncio.gather(*(evaluate_alert_rule(rule_id) for rule_id in rule_ids))
    return len(rule_ids)


async def alert_scheduler_loop() -> None:
    interval = max(2, int(getattr(settings, "alert_scheduler_poll_seconds", 10)))
    while True:
        try:
            await process_due_alerts()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("alert_scheduler_failed", error=str(exc))
        await asyncio.sleep(interval)
