from __future__ import annotations

import asyncio
import json
import os
import socket
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from infra.cache.redis_client import get_queue_redis
from infra.observability.logger import get_logger
from infra.responses.repository import (
    add_outbox,
    append_event,
    claim_response,
    release_lease,
    renew_lease,
)
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import (
    ChatSession,
    GoalCheckpoint,
    GoalRun,
    ResponseItem,
    ResponseModelCall,
    ResponseOutbox,
    ResponseRecord,
    TaskRun,
)
from kernel.agent_loop.memory_learner import MemoryLearner
from kernel.agent_loop.runner import AgentLoop

logger = get_logger(__name__)
STREAM = "opentrace:responses:v2"
GROUP = "opentrace-response-workers"
OWNER = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


async def dispatch_outbox(*, limit: int = 100) -> int:
    """Publish committed jobs. PostgreSQL remains authoritative on failure."""
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ResponseOutbox)
                .where(ResponseOutbox.status == "pending", ResponseOutbox.available_at <= now)
                .order_by(ResponseOutbox.created_at)
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        ).scalars().all()
        if not rows:
            return 0
        published = 0
        try:
            redis = await get_queue_redis()
            for row in rows:
                try:
                    await redis.xadd(
                        STREAM,
                        {"data": json.dumps({"outbox_id": row.id, **dict(row.payload or {})})},
                        maxlen=100_000,
                    )
                    row.status = "published"
                    row.published_at = now
                    row.last_error = None
                    published += 1
                except Exception as exc:  # noqa: BLE001
                    row.attempt_count = int(row.attempt_count or 0) + 1
                    row.last_error = str(exc)[:1000]
                    row.available_at = now + timedelta(seconds=min(60, 2 ** min(row.attempt_count, 6)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("response_outbox_redis_unavailable", error=str(exc))
        await db.commit()
        return published


async def execute_response(response_id: str | None = None) -> bool:
    async with AsyncSessionLocal() as db:
        response = await claim_response(db, owner=OWNER, response_id=response_id)
        if response is None:
            return False
        response_id = response.id
        await append_event(db, response_id=response.id, event_type="response.in_progress", payload={"status": "in_progress", "attempt": response.attempt_count})
        await db.commit()

    heartbeat = asyncio.create_task(_heartbeat(response_id))
    try:
        async with AsyncSessionLocal() as db:
            response = await db.get(ResponseRecord, response_id, with_for_update=True)
            if response is None or response.lease_owner != OWNER or response.status == "cancelled":
                return False
            if response.goal_id:
                goal = await db.get(GoalRun, response.goal_id)
                if goal:
                    goal.status = "in_progress"
                    if not dict(goal.plan or {}).get("steps"):
                        goal.plan = {
                            "steps": ["理解目标与成功标准", "执行并收集证据", "验证结果并交付"],
                            "success_criteria": goal.success_criteria,
                        }
                    started = await db.scalar(
                        select(GoalCheckpoint.id).where(
                            GoalCheckpoint.goal_id == goal.id,
                            GoalCheckpoint.step_number == 0,
                        )
                    )
                    if started is None:
                        db.add(GoalCheckpoint(
                            id=str(uuid.uuid4()), goal_id=goal.id, step_number=0,
                            status="in_progress", summary="Goal 已由统一 Agent Loop 接管。",
                            state={"response_id": response.id, "attempt": response.attempt_count},
                        ))
                    await db.commit()

            async def emit(event_type: str, payload: dict) -> None:
                await append_event(db, response_id=response_id, event_type=event_type, payload=payload)
                await db.commit()

            result = await AgentLoop().run(db, response=response, emit=emit)
            if result.status == "requires_action":
                if response.goal_id:
                    goal = await db.get(GoalRun, response.goal_id)
                    if goal:
                        goal.status = "requires_action"
                await release_lease(db, response)
                await db.commit()
                return True

            await db.refresh(response)
            if response.status == "cancelled":
                await release_lease(db, response)
                await db.commit()
                return False

            next_item = await _next_item_sequence(db, response_id)
            message = ResponseItem(
                id=f"item_{uuid.uuid4().hex}", response_id=response_id,
                sequence_number=next_item, item_type="message", role="assistant",
                content=result.content, payload=result.metadata,
            )
            db.add(message)
            response.status = "completed"
            response.model = result.model
            response.completed_at = datetime.now(UTC)
            response.response_metadata = {**dict(response.response_metadata or {}), **result.metadata, "intent": result.intent.to_dict() if result.intent else None}
            await release_lease(db, response)
            await append_event(db, response_id=response_id, event_type="response.output_item.done", payload={"item_id": message.id, "item_type": "message", "role": "assistant", "content": result.content})
            await append_event(db, response_id=response_id, event_type="response.completed", payload={"status": "completed", "content": result.content, "model": result.model, "metadata": result.metadata})
            await _persist_model_calls(db, response_id, result.metadata)
            session = await db.get(ChatSession, response.conversation_id)
            if session:
                session.active_response_id = response.id
                session.turn_count = int(session.turn_count or 0) + 1
                session.last_active = datetime.now(UTC)
            if response.goal_id:
                goal = await db.get(GoalRun, response.goal_id)
                if goal:
                    goal.status = "completed"
                    goal.response_id = response.id
                    goal.current_step = int(goal.current_step or 0) + 1
                    goal.completed_at = datetime.now(UTC)
                    db.add(GoalCheckpoint(
                        id=str(uuid.uuid4()), goal_id=goal.id, step_number=goal.current_step,
                        status="completed", summary=result.content[:2000],
                        state={"response_id": response.id, "model": result.model},
                    ))
            task_run = await db.scalar(select(TaskRun).where(TaskRun.response_id == response.id))
            if task_run:
                task_run.status = "succeeded"
                task_run.output = result.content
                task_run.finished_at = datetime.now(UTC)
            await db.commit()
        try:
            async with AsyncSessionLocal() as summary_db:
                from kernel.agent_loop.summarizer import ConversationSummarizer

                summary_response = await summary_db.get(ResponseRecord, response_id)
                if summary_response:
                    await ConversationSummarizer().summarize(summary_db, response=summary_response)
        except Exception as exc:  # noqa: BLE001
            logger.warning("conversation_summary_failed", response_id=response_id, error=str(exc))
        try:
            async with AsyncSessionLocal() as memory_db:
                memory_response = await memory_db.get(ResponseRecord, response_id)
                if memory_response:
                    await MemoryLearner().learn(memory_db, response=memory_response)
        except Exception as exc:  # noqa: BLE001
            logger.warning("response_memory_learning_failed", response_id=response_id, error=str(exc))
        return True
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("response_execution_failed", response_id=response_id, error=str(exc))
        async with AsyncSessionLocal() as db:
            response = await db.get(ResponseRecord, response_id, with_for_update=True)
            if response and response.status not in {"cancelled", "completed", "requires_action"}:
                response.status = "failed" if response.attempt_count >= response.max_attempts else "queued"
                response.error_code = "response_execution_failed"
                response.error_message = "响应执行失败，请稍后重试。"
                if response.status == "failed":
                    response.completed_at = datetime.now(UTC)
                    await append_event(db, response_id=response_id, event_type="response.failed", payload={"status": "failed", "code": response.error_code, "message": response.error_message})
                    if response.goal_id:
                        goal = await db.get(GoalRun, response.goal_id)
                        if goal:
                            goal.status = "failed"
                    task_run = await db.scalar(select(TaskRun).where(TaskRun.response_id == response.id))
                    if task_run:
                        task_run.status = "failed"
                        task_run.error = response.error_message
                        task_run.finished_at = datetime.now(UTC)
                else:
                    add_outbox(db, response_id=response_id, suffix=f"retry-{response.attempt_count}")
                await release_lease(db, response)
                await db.commit()
        return False
    finally:
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass


async def _heartbeat(response_id: str) -> None:
    while True:
        await asyncio.sleep(30)
        async with AsyncSessionLocal() as db:
            if not await renew_lease(db, response_id, OWNER):
                return


async def _next_item_sequence(db, response_id: str) -> int:
    from sqlalchemy import func
    current = await db.scalar(select(func.max(ResponseItem.sequence_number)).where(ResponseItem.response_id == response_id))
    return int(current if current is not None else -1) + 1


async def _persist_model_calls(db, response_id: str, metadata: dict) -> None:
    for call in metadata.get("model_calls") or []:
        if not isinstance(call, dict) or not call.get("id"):
            continue
        db.add(ResponseModelCall(
            id=f"mcall_{uuid.uuid4().hex}", response_id=response_id,
            call_id=str(call["id"]), role=str(call.get("role") or "query"),
            model=str(call.get("model") or "") or None,
            latency_ms=int(call["latency_ms"]) if call.get("latency_ms") is not None else None,
            call_metadata={key: value for key, value in call.items() if key not in {"id", "role", "model", "latency_ms"}},
        ))


async def _ensure_group() -> None:
    redis = await get_queue_redis()
    try:
        await redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception as exc:  # BUSYGROUP is expected after first worker.
        if "BUSYGROUP" not in str(exc):
            raise


async def _reclaim_pending(redis, *, idle_ms: int = 150_000, count: int = 20) -> int:
    """Reclaim messages abandoned by a crashed worker after its DB lease expires."""
    pending = await redis.xpending_range(STREAM, GROUP, min="-", max="+", count=count)
    message_ids = [
        item.get("message_id")
        for item in pending
        if item.get("message_id") and int(item.get("time_since_delivered", 0) or 0) >= idle_ms
    ]
    if not message_ids:
        return 0
    claimed = await redis.xclaim(
        STREAM,
        GROUP,
        OWNER,
        min_idle_time=idle_ms,
        message_ids=message_ids,
    )
    processed = 0
    for message_id, fields in claimed:
        data = json.loads(str(fields.get("data") or "{}"))
        await execute_response(str(data.get("response_id") or "") or None)
        await redis.xack(STREAM, GROUP, message_id)
        processed += 1
    return processed


async def response_worker_loop() -> None:
    try:
        await _ensure_group()
    except Exception as exc:  # noqa: BLE001
        logger.warning("response_stream_setup_failed_using_db_poll", error=str(exc))
    while True:
        try:
            await dispatch_outbox()
            processed = False
            try:
                redis = await get_queue_redis()
                if await _reclaim_pending(redis):
                    processed = True
                rows = await redis.xreadgroup(GROUP, OWNER, streams={STREAM: ">"}, count=10, block=1000)
                for _, entries in rows:
                    for message_id, fields in entries:
                        data = json.loads(str(fields.get("data") or "{}"))
                        await execute_response(str(data.get("response_id") or "") or None)
                        await redis.xack(STREAM, GROUP, message_id)
                        processed = True
            except Exception as exc:  # noqa: BLE001
                logger.debug("response_stream_read_failed", error=str(exc))
            # DB claim is the recovery path for lost Redis messages and Redis outages.
            if not processed:
                await execute_response()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("response_worker_iteration_failed", error=str(exc))
            await asyncio.sleep(1)
