from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from infra.audit.logger import write_audit_log
from infra.errors import AppException, ErrorCodes
from infra.message_bus.bus import bus
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import TaskDefinition, TaskRun, TaskNotification, User

router = APIRouter()

_ACTIVE_TASK_LOOPS: dict[str, asyncio.Task] = {}


class TaskCreateRequest(BaseModel):
    description: str = Field(..., min_length=3, max_length=4000)


class TaskActionRequest(BaseModel):
    task_id: str


def _parse_schedule_from_nl(desc: str) -> tuple[str, dict[str, Any], str]:
    d = desc.strip()
    lowered = d.lower()
    if "每小时" in d or "every hour" in lowered:
        return "interval", {"seconds": 3600}, d[:80]
    m = re.search(r"every\s+(\d+)\s+minutes?", lowered)
    if m:
        mins = max(1, int(m.group(1)))
        return "interval", {"seconds": mins * 60}, d[:80]
    if "每天" in d or "daily" in lowered:
        return "cron", {"hour": 8, "minute": 0}, d[:80]
    if "当" in d or "when" in lowered:
        return "event", {"event": "external_trigger"}, d[:80]
    return "interval", {"seconds": 1800}, d[:80]


async def _run_task_once(task: TaskDefinition) -> None:
    from infra.storage.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        run = TaskRun(
            id=str(uuid.uuid4()),
            task_id=task.id,
            user_id=task.user_id,
            status="running",
        )
        db.add(run)
        await db.commit()

        try:
            output = f"[auto-run] {task.description[:200]}"
            run.status = "succeeded"
            run.output = output
            run.finished_at = datetime.now(timezone.utc)

            r = await db.execute(select(TaskDefinition).where(TaskDefinition.id == task.id))
            td = r.scalar_one_or_none()
            if td:
                td.last_run_at = datetime.now(timezone.utc)
                cfg = json.loads(td.trigger_config_json or "{}")
                if td.trigger_type == "interval":
                    sec = int(cfg.get("seconds", 1800))
                    td.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=sec)
            await db.commit()

            note = TaskNotification(
                id=str(uuid.uuid4()),
                user_id=task.user_id,
                task_id=task.id,
                run_id=run.id,
                level="info",
                title="任务已完成",
                body=output[:500],
                read=False,
            )
            db.add(note)
            await db.commit()
            await bus.publish("tasks.events", {"type": "task.completed", "task_id": task.id, "run_id": run.id})
        except Exception as exc:  # noqa: BLE001
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = datetime.now(timezone.utc)
            note = TaskNotification(
                id=str(uuid.uuid4()),
                user_id=task.user_id,
                task_id=task.id,
                run_id=run.id,
                level="error",
                title="任务执行失败",
                body=str(exc)[:500],
                read=False,
            )
            db.add(note)
            await db.commit()
            await bus.publish("tasks.events", {"type": "task.failed", "task_id": task.id, "run_id": run.id, "error": str(exc)})


async def _task_loop(task_id: str) -> None:
    from infra.storage.database import AsyncSessionLocal

    while True:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(TaskDefinition).where(TaskDefinition.id == task_id))
            td = r.scalar_one_or_none()
            if td is None or td.status != "active":
                return
            trigger_cfg = json.loads(td.trigger_config_json or "{}")
            trigger_type = td.trigger_type

        if trigger_type == "interval":
            await _run_task_once(td)
            await asyncio.sleep(int(trigger_cfg.get("seconds", 1800)))
        elif trigger_type == "cron":
            # lightweight: daily at fixed hour/minute
            now = datetime.now(timezone.utc)
            target = now.replace(hour=int(trigger_cfg.get("hour", 8)), minute=int(trigger_cfg.get("minute", 0)), second=0, microsecond=0)
            if target <= now:
                target = target + timedelta(days=1)
            await asyncio.sleep(max(1, int((target - now).total_seconds())))
            await _run_task_once(td)
        else:
            # event-driven: idle until external trigger integration
            await asyncio.sleep(10)


def _start_task_loop(task_id: str) -> None:
    if task_id in _ACTIVE_TASK_LOOPS and not _ACTIVE_TASK_LOOPS[task_id].done():
        return
    _ACTIVE_TASK_LOOPS[task_id] = asyncio.create_task(_task_loop(task_id))


def _stop_task_loop(task_id: str) -> None:
    t = _ACTIVE_TASK_LOOPS.get(task_id)
    if t and not t.done():
        t.cancel()


@router.post("/tasks")
async def create_task(req: TaskCreateRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    trigger_type, trigger_cfg, title = _parse_schedule_from_nl(req.description)
    task = TaskDefinition(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        title=title,
        description=req.description,
        trigger_type=trigger_type,
        trigger_config_json=json.dumps(trigger_cfg, ensure_ascii=False),
        status="active",
        next_run_at=datetime.now(timezone.utc),
    )
    db.add(task)
    await db.commit()

    _start_task_loop(task.id)
    await write_audit_log(
        user_id=current_user.id,
        action="task.create",
        resource_type="task",
        resource_id=task.id,
        payload={"trigger_type": task.trigger_type, "trigger_config": trigger_cfg, "description": req.description[:500]},
    )
    await bus.publish("tasks.events", {"type": "task.created", "task_id": task.id, "user_id": current_user.id})
    return {"task_id": task.id, "title": task.title, "trigger_type": task.trigger_type, "trigger_config": trigger_cfg, "status": task.status}


@router.get("/tasks")
async def list_tasks(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    r = await db.execute(select(TaskDefinition).where(TaskDefinition.user_id == current_user.id).order_by(TaskDefinition.created_at.desc()))
    items = r.scalars().all()
    return {
        "items": [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "trigger_type": t.trigger_type,
                "trigger_config": json.loads(t.trigger_config_json or "{}"),
                "status": t.status,
                "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
                "next_run_at": t.next_run_at.isoformat() if t.next_run_at else None,
            }
            for t in items
        ]
    }


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    r = await db.execute(select(TaskDefinition).where(TaskDefinition.id == task_id, TaskDefinition.user_id == current_user.id))
    t = r.scalar_one_or_none()
    if t is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="task not found")

    rr = await db.execute(select(TaskRun).where(TaskRun.task_id == task_id).order_by(TaskRun.started_at.desc()).limit(20))
    runs = rr.scalars().all()
    return {
        "task": {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "trigger_type": t.trigger_type,
            "trigger_config": json.loads(t.trigger_config_json or "{}"),
            "status": t.status,
        },
        "runs": [
            {
                "id": x.id,
                "status": x.status,
                "output": x.output,
                "error": x.error,
                "started_at": x.started_at.isoformat() if x.started_at else None,
                "finished_at": x.finished_at.isoformat() if x.finished_at else None,
            }
            for x in runs
        ],
    }


@router.post("/tasks/pause")
async def pause_task(req: TaskActionRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    r = await db.execute(select(TaskDefinition).where(TaskDefinition.id == req.task_id, TaskDefinition.user_id == current_user.id))
    t = r.scalar_one_or_none()
    if t is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="task not found")
    t.status = "paused"
    await db.commit()
    _stop_task_loop(t.id)
    await bus.publish("tasks.events", {"type": "task.paused", "task_id": t.id, "user_id": current_user.id})
    return {"task_id": t.id, "status": t.status}


@router.post("/tasks/resume")
async def resume_task(req: TaskActionRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    r = await db.execute(select(TaskDefinition).where(TaskDefinition.id == req.task_id, TaskDefinition.user_id == current_user.id))
    t = r.scalar_one_or_none()
    if t is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="task not found")
    t.status = "active"
    await db.commit()
    _start_task_loop(t.id)
    await bus.publish("tasks.events", {"type": "task.resumed", "task_id": t.id, "user_id": current_user.id})
    return {"task_id": t.id, "status": t.status}


@router.post("/tasks/cancel")
async def cancel_task(req: TaskActionRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    r = await db.execute(select(TaskDefinition).where(TaskDefinition.id == req.task_id, TaskDefinition.user_id == current_user.id))
    t = r.scalar_one_or_none()
    if t is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="task not found")
    t.status = "cancelled"
    await db.commit()
    _stop_task_loop(t.id)
    await bus.publish("tasks.events", {"type": "task.cancelled", "task_id": t.id, "user_id": current_user.id})
    return {"task_id": t.id, "status": t.status}


@router.post("/tasks/events/trigger")
async def trigger_event_task(event_name: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    r = await db.execute(
        select(TaskDefinition).where(
            TaskDefinition.user_id == current_user.id,
            TaskDefinition.trigger_type == "event",
            TaskDefinition.status == "active",
        )
    )
    tasks = r.scalars().all()
    triggered = 0
    for t in tasks:
        cfg = json.loads(t.trigger_config_json or "{}")
        if cfg.get("event") in {event_name, "external_trigger"}:
            await _run_task_once(t)
            triggered += 1
    await write_audit_log(
        user_id=current_user.id,
        action="task.event.trigger",
        resource_type="task_event",
        resource_id=event_name,
        payload={"event": event_name, "triggered": triggered},
    )
    return {"event": event_name, "triggered": triggered}


@router.get("/tasks/notifications")
async def list_notifications(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    r = await db.execute(
        select(TaskNotification)
        .where(TaskNotification.user_id == current_user.id)
        .order_by(TaskNotification.created_at.desc())
        .limit(100)
    )
    items = r.scalars().all()
    return {
        "items": [
            {
                "id": n.id,
                "task_id": n.task_id,
                "run_id": n.run_id,
                "level": n.level,
                "title": n.title,
                "body": n.body,
                "read": n.read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in items
        ]
    }


@router.post("/tasks/notifications/read")
async def mark_notification_read(notification_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    r = await db.execute(
        select(TaskNotification).where(
            TaskNotification.id == notification_id,
            TaskNotification.user_id == current_user.id,
        )
    )
    n = r.scalar_one_or_none()
    if n is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="notification not found")
    n.read = True
    await db.commit()
    return {"id": n.id, "read": n.read}
