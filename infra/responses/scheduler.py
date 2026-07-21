from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infra.observability.logger import get_logger
from infra.responses.repository import add_outbox, append_event
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import (
    ChatSession,
    ResponseItem,
    ResponseRecord,
    TaskDefinition,
    TaskNotification,
    TaskRun,
    UserMemory,
)

logger = get_logger(__name__)


def task_request_id(task_id: str, scheduled_for: datetime) -> str:
    """生成满足 Responses 64 字符上限的稳定调度请求 ID。"""
    raw = f"{task_id}:{scheduled_for.isoformat()}"
    return f"task:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:40]}"


def parse_schedule_expression(expression: str) -> str:
    """Parse supported recurring natural-language forms without guessing."""
    value = expression.strip().lower()
    time_match = re.search(r"(\d{1,2})(?::(\d{1,2})|点(\d{1,2})?)", value)
    at_match = re.search(r"\bat\s+(\d{1,2})(?:\s*:\s*(\d{1,2}))?", value)
    matched_time = time_match or at_match
    hour = int(matched_time.group(1)) if matched_time else 9
    minute = (
        int((matched_time.group(2) or (matched_time.group(3) if time_match else None)) or 0)
        if matched_time
        else 0
    )
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("invalid schedule time")
    if value in {"hourly", "每小时"}:
        return "FREQ=HOURLY"
    interval_match = re.search(r"(?:每隔|every)\s*(\d+)\s*(?:个)?(?:小时|hours?)", value)
    if interval_match:
        interval = int(interval_match.group(1))
        if not 1 <= interval <= 168:
            raise ValueError("invalid hourly interval")
        return f"FREQ=HOURLY;INTERVAL={interval}"
    suffix = f"BYHOUR={hour};BYMINUTE={minute};BYSECOND=0"
    month_day_match = re.search(r"(?:每月|monthly)\s*(\d{1,2})(?:号|日|st|nd|rd|th)?", value)
    if month_day_match:
        month_day = int(month_day_match.group(1))
        if not 1 <= month_day <= 31:
            raise ValueError("invalid day of month")
        return f"FREQ=MONTHLY;BYMONTHDAY={month_day};{suffix}"
    if any(token in value for token in ("工作日", "weekday", "weekdays")):
        return f"FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;{suffix}"
    weekdays = {
        "周一": "MO",
        "星期一": "MO",
        "monday": "MO",
        "周二": "TU",
        "星期二": "TU",
        "tuesday": "TU",
        "周三": "WE",
        "星期三": "WE",
        "wednesday": "WE",
        "周四": "TH",
        "星期四": "TH",
        "thursday": "TH",
        "周五": "FR",
        "星期五": "FR",
        "friday": "FR",
        "周六": "SA",
        "星期六": "SA",
        "saturday": "SA",
        "周日": "SU",
        "星期日": "SU",
        "星期天": "SU",
        "sunday": "SU",
    }
    selected_days = list(dict.fromkeys(day for token, day in weekdays.items() if token in value))
    if selected_days:
        return f"FREQ=WEEKLY;BYDAY={','.join(selected_days)};{suffix}"
    if any(token in value for token in ("每天", "每日", "daily", "every day")):
        return f"FREQ=DAILY;{suffix}"
    raise ValueError("unsupported schedule expression")


def next_occurrence(
    rrule_value: str,
    timezone_name: str,
    *,
    after: datetime | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> datetime | None:
    occurrences = next_occurrences(
        rrule_value,
        timezone_name,
        after=after,
        starts_at=starts_at,
        ends_at=ends_at,
        limit=1,
    )
    return occurrences[0] if occurrences else None


def next_occurrences(
    rrule_value: str,
    timezone_name: str,
    *,
    after: datetime | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    limit: int = 5,
) -> list[datetime]:
    """计算有界 RRULE 的后续执行时间，统一返回 UTC。"""
    from dateutil.rrule import rrulestr  # type: ignore[import-untyped]

    zone = ZoneInfo(timezone_name)
    base = after or datetime.now(UTC)
    local_base = base.astimezone(zone)
    local_start = (starts_at or base).astimezone(zone)
    local_end = ends_at.astimezone(zone) if ends_at else None
    rule = rrulestr(rrule_value, dtstart=local_start)
    results: list[datetime] = []
    cursor = local_base
    for _ in range(max(1, min(limit, 20))):
        result = rule.after(cursor, inc=False)
        if result is None:
            break
        if result.tzinfo is None:
            result = result.replace(tzinfo=zone)
        if local_end is not None and result > local_end:
            break
        results.append(result.astimezone(UTC))
        cursor = result
    return results


def task_schedule_bounds(task: TaskDefinition) -> tuple[datetime | None, datetime | None]:
    """从兼容的 trigger JSON 中读取任务有效期。"""
    try:
        config = json.loads(getattr(task, "trigger_config_json", "{}") or "{}")
    except (TypeError, ValueError):
        return None, None

    def _parse(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    return _parse(config.get("starts_at")), _parse(config.get("ends_at"))


async def enqueue_due_tasks(*, limit: int = 20) -> int:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        tasks = (
            (
                await db.execute(
                    select(TaskDefinition)
                    .where(
                        TaskDefinition.status == "active",
                        TaskDefinition.next_run_at.is_not(None),
                        TaskDefinition.next_run_at <= now,
                    )
                    .order_by(TaskDefinition.next_run_at)
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        count = 0
        for task in tasks:
            scheduled_for = task.next_run_at
            if scheduled_for is None:
                continue
            try:
                async with db.begin_nested():
                    starts_at, ends_at = task_schedule_bounds(task)
                    run = await queue_task_run(
                        db,
                        task,
                        scheduled_for=scheduled_for,
                        trigger="scheduled",
                    )
                    task.next_run_at = (
                        next_occurrence(
                            task.rrule or "",
                            task.timezone,
                            after=scheduled_for,
                            starts_at=starts_at,
                            ends_at=ends_at,
                        )
                        if task.rrule
                        else None
                    )
                    if task.next_run_at is None and ends_at is not None:
                        task.status = "completed"
                    if run is not None:
                        count += 1
            except Exception as exc:  # noqa: BLE001
                # 单条损坏的历史任务不能阻塞同一批次中的其他任务。
                task.status = "paused"
                task.next_run_at = None
                db.add(
                    TaskNotification(
                        id=str(uuid.uuid4()),
                        user_id=task.user_id,
                        task_id=task.id,
                        level="error",
                        title=f"{task.title} 已自动暂停",
                        body=f"任务无法入队：{str(exc)[:1000]}",
                    )
                )
                logger.warning("scheduled_task_enqueue_failed", task_id=task.id, error=str(exc))
        await db.commit()
        return count


async def queue_task_run(
    db: AsyncSession,
    task: TaskDefinition,
    *,
    scheduled_for: datetime,
    trigger: str,
) -> TaskRun | None:
    """在同一事务内持久化一次任务运行与对应 Response。"""
    existing = await db.scalar(
        select(TaskRun.id).where(
            TaskRun.task_id == task.id,
            TaskRun.scheduled_for == scheduled_for,
        )
    )
    if existing:
        return None

    run = TaskRun(
        id=str(uuid.uuid4()),
        task_id=task.id,
        user_id=task.user_id,
        status="queued",
        scheduled_for=scheduled_for,
    )
    db.add(run)
    await db.flush()

    session = None
    if task.conversation_id:
        session = await db.scalar(
            select(ChatSession).where(
                ChatSession.id == task.conversation_id,
                ChatSession.user_id == task.user_id,
                ChatSession.tenant_id == task.tenant_id,
                ChatSession.workspace_id == task.workspace_id,
            )
        )
    if session is None:
        session = ChatSession(
            id=str(uuid.uuid4()),
            user_id=task.user_id,
            title=task.title,
            display_title=task.title,
            tenant_id=task.tenant_id,
            workspace_id=task.workspace_id,
            org_id="default",
            project_id=task.project_id,
        )
        db.add(session)
        await db.flush()
        task.conversation_id = session.id

    response_id = f"resp_{uuid.uuid4().hex}"
    response = ResponseRecord(
        id=response_id,
        conversation_id=session.id,
        user_id=task.user_id,
        tenant_id=task.tenant_id,
        workspace_id=task.workspace_id,
        parent_response_id=session.active_response_id,
        request_id=task_request_id(task.id, scheduled_for),
        idempotency_key=f"task:{task.id}:{scheduled_for.isoformat()}",
        status="queued",
        mode="background",
        request_payload={
            "input": task.description,
            "background": True,
            "stream": False,
            "store": False,
            "tools": [],
            "tool_choice": "auto",
            "parallel_tool_calls": True,
            "opentrace": {
                "project_id": task.project_id,
                "execution_profile": "auto",
                "memory_mode": "enabled",
                "data_source_ids": [],
            },
        },
        response_metadata={
            "scheduled_task_id": task.id,
            "task_run_id": run.id,
            "task_trigger": trigger,
        },
    )
    db.add(response)
    await db.flush()
    db.add(
        ResponseItem(
            id=f"item_{uuid.uuid4().hex}",
            response_id=response_id,
            sequence_number=0,
            item_type="input_message",
            role="user",
            content=task.description,
            payload={"scheduled_task_id": task.id, "task_trigger": trigger},
        )
    )
    await append_event(
        db,
        response_id=response_id,
        event_type="response.created",
        payload={
            "response_id": response_id,
            "status": "queued",
            "scheduled_task_id": task.id,
            "task_trigger": trigger,
        },
    )
    add_outbox(db, response_id=response_id, suffix=f"task-{run.id}")
    run.response_id = response_id
    session.active_response_id = response_id
    task.last_run_at = datetime.now(UTC)
    return run


async def expire_transient_state(*, limit: int = 200) -> tuple[int, int]:
    """Expire temporary conversations and learned memories in bounded batches."""
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        sessions = (
            (
                await db.execute(
                    select(ChatSession)
                    .where(
                        ChatSession.is_temporary.is_(True),
                        ChatSession.expires_at.is_not(None),
                        ChatSession.expires_at <= now,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        for session in sessions:
            await db.delete(session)
        memory_result = await db.execute(
            update(UserMemory)
            .where(
                UserMemory.status == "active",
                UserMemory.expires_at.is_not(None),
                UserMemory.expires_at <= now,
            )
            .values(status="expired", enabled=False)
        )
        await db.commit()
        return len(sessions), int(memory_result.rowcount or 0)


async def scheduler_loop() -> None:
    while True:
        try:
            await enqueue_due_tasks()
            await expire_transient_state()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("scheduled_task_poll_failed", error=str(exc))
        await asyncio.sleep(5)
