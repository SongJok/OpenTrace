from __future__ import annotations

import asyncio
import json
import os
import socket
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from infra.cache.redis_client import get_queue_redis
from infra.config.settings import settings
from infra.model_settings import load_runtime_llm_profile
from infra.observability.logger import get_logger
from infra.observability.metrics import (
    RESPONSE_COMPLETED_TOTAL,
    RESPONSE_END_TO_END_DURATION,
    RESPONSE_FIRST_EVENT_DURATION,
    RESPONSE_LEASE_RECOVERY_TOTAL,
    RESPONSE_OUTBOX_PENDING,
    RESPONSE_QUEUE_DEPTH,
    WORKER_ITERATION_FAILURES_TOTAL,
)
from infra.observability.tracer import get_tracer
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
    TaskDefinition,
    TaskNotification,
    TaskRun,
)
from kernel.agent_loop.memory_learner import MemoryLearner
from kernel.agent_loop.runner import AgentLoop
from model.model_gateway.runtime_config import use_runtime_llm_profile
from tenant.tenant_rls import set_worker_session

logger = get_logger(__name__)
tracer = get_tracer(__name__)
STREAM = "opentrace:responses:v2"
GROUP = "opentrace-response-workers"
OWNER = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
_TENANT_SEMAPHORES: dict[str, asyncio.Semaphore] = {}
_INVALID_TERMINAL_CONTENT = frozenset({"", "null", "undefined", "nil"})


def _valid_terminal_content(value: object) -> str | None:
    text = str(value or "").strip()
    if text.casefold() in _INVALID_TERMINAL_CONTENT:
        return None
    return text


def _tenant_semaphore(tenant_id: str) -> asyncio.Semaphore:
    key = tenant_id or "default"
    semaphore = _TENANT_SEMAPHORES.get(key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(max(1, int(settings.response_worker_tenant_concurrency)))
        _TENANT_SEMAPHORES[key] = semaphore
    return semaphore


async def _update_task_run(
    db,
    response: ResponseRecord,
    *,
    status: str,
    output: str | None = None,
    error: str | None = None,
    finished: bool = False,
) -> None:
    """同步定时任务运行状态，并生成一次用户可见通知。"""
    task_run = await db.scalar(select(TaskRun).where(TaskRun.response_id == response.id))
    if task_run is None:
        return
    task_run.status = status
    task_run.output = output
    task_run.error = error
    task_run.finished_at = datetime.now(UTC) if finished else None

    labels = {
        "succeeded": ("success", "已完成"),
        "incomplete": ("warning", "未完整完成"),
        "requires_action": ("warning", "等待确认"),
        "cancelled": ("info", "已取消"),
        "failed": ("error", "执行失败"),
    }
    level, label = labels.get(status, ("info", status))
    title = await db.scalar(
        select(TaskDefinition.title).where(TaskDefinition.id == task_run.task_id)
    )
    notification_title = f"{title or '定时任务'}{label}"
    existing = await db.scalar(
        select(TaskNotification.id).where(
            TaskNotification.run_id == task_run.id,
            TaskNotification.title == notification_title,
        )
    )
    if existing is None:
        body = error or output or "任务状态已更新。"
        db.add(
            TaskNotification(
                id=str(uuid.uuid4()),
                user_id=task_run.user_id,
                task_id=task_run.task_id,
                run_id=task_run.id,
                level=level,
                title=notification_title,
                body=body[:2000],
            )
        )


async def dispatch_outbox(*, limit: int = 100) -> int:
    """Publish committed jobs. PostgreSQL remains authoritative on failure."""
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        await set_worker_session(db)
        queue_depth = int(
            await db.scalar(
                select(func.count(ResponseRecord.id)).where(
                    ResponseRecord.status.in_(("queued", "in_progress"))
                )
            )
            or 0
        )
        pending_outbox = int(
            await db.scalar(
                select(func.count(ResponseOutbox.id)).where(ResponseOutbox.status == "pending")
            )
            or 0
        )
        RESPONSE_QUEUE_DEPTH.set(queue_depth)
        RESPONSE_OUTBOX_PENDING.set(pending_outbox)
        if queue_depth >= max(1, int(settings.response_worker_max_queue_depth)):
            logger.warning("response_worker_backpressure", queue_depth=queue_depth)
            return 0
        rows = (
            (
                await db.execute(
                    select(ResponseOutbox)
                    .where(ResponseOutbox.status == "pending", ResponseOutbox.available_at <= now)
                    .order_by(ResponseOutbox.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
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
                    row.available_at = now + timedelta(
                        seconds=min(60, 2 ** min(row.attempt_count, 6))
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("response_outbox_redis_unavailable", error=str(exc))
        await db.commit()
        return published


async def execute_response(response_id: str | None = None) -> bool:
    async with AsyncSessionLocal() as db:
        await set_worker_session(db)
        response = await claim_response(db, owner=OWNER, response_id=response_id)
        if response is None:
            return False
        response_id = response.id
        await append_event(
            db,
            response_id=response.id,
            event_type="response.in_progress",
            payload={"status": "in_progress", "attempt": response.attempt_count},
        )
        await db.commit()
        if response.created_at:
            RESPONSE_FIRST_EVENT_DURATION.observe(
                max(0.0, (datetime.now(UTC) - response.created_at).total_seconds())
            )

    heartbeat = asyncio.create_task(_heartbeat(response_id))
    tenant_limit = _tenant_semaphore(response.tenant_id)
    deterministic_memory_projected = False
    await tenant_limit.acquire()
    try:
        async with AsyncSessionLocal() as db:
            await set_worker_session(db)
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
                        db.add(
                            GoalCheckpoint(
                                id=str(uuid.uuid4()),
                                goal_id=goal.id,
                                step_number=0,
                                status="in_progress",
                                summary="Goal 已由统一 Agent Loop 接管。",
                                state={
                                    "response_id": response.id,
                                    "attempt": response.attempt_count,
                                },
                            )
                        )
                    await db.commit()

            async def emit(event_type: str, payload: dict) -> None:
                await append_event(
                    db, response_id=response_id, event_type=event_type, payload=payload
                )
                await db.commit()

            runtime_profile = await load_runtime_llm_profile(
                db,
                user_id=response.user_id,
                tenant_id=response.tenant_id,
                workspace_id=response.workspace_id,
                selection=(response.response_metadata or {}).get("model_selection"),
            )
            if runtime_profile is not None:
                await emit(
                    "opentrace.model.configuration",
                    {
                        "source": runtime_profile.source,
                        "provider": runtime_profile.provider,
                        "model": runtime_profile.model,
                    },
                )
            with use_runtime_llm_profile(runtime_profile):
                with tracer.start_as_current_span("response.agent_loop") as span:
                    span.set_attribute("opentrace.response.id", response.id)
                    span.set_attribute("opentrace.tenant.id", response.tenant_id)
                    span.set_attribute("opentrace.response.attempt", response.attempt_count)
                    if runtime_profile is not None:
                        span.set_attribute("opentrace.llm.source", runtime_profile.source)
                        span.set_attribute("opentrace.llm.model", runtime_profile.model)
                    result = await AgentLoop().run(db, response=response, emit=emit)
            if result.status == "requires_action":
                if response.goal_id:
                    goal = await db.get(GoalRun, response.goal_id)
                    if goal:
                        goal.status = "requires_action"
                await _update_task_run(
                    db,
                    response,
                    status="requires_action",
                    output=result.content,
                )
                await release_lease(db, response)
                await db.commit()
                return True
            if result.status == "cancelled":
                await _update_task_run(db, response, status="cancelled", finished=True)
                await release_lease(db, response)
                await db.commit()
                return False

            await db.refresh(response)
            if response.status == "cancelled":
                await release_lease(db, response)
                await db.commit()
                return False

            terminal_content = _valid_terminal_content(result.content)
            if terminal_content is None:
                result.status = "incomplete"
                result.content = "本次模型未返回有效回答，请点击“重新生成”或稍后重试。"
                result.metadata = {
                    **dict(result.metadata or {}),
                    "incomplete_details": {
                        **dict((result.metadata or {}).get("incomplete_details") or {}),
                        "reason": "invalid_empty_model_output",
                    },
                }
                await emit(
                    "response.output_text.done",
                    {"text": result.content, "recovered_from_invalid_output": True},
                )

            query = AgentLoop._query(dict(response.request_payload or {}))
            if MemoryLearner.deterministic_candidates(query):
                try:
                    async with AsyncSessionLocal() as memory_db:
                        await set_worker_session(memory_db)
                        memory_response = await memory_db.get(ResponseRecord, response_id)
                        if memory_response:
                            with use_runtime_llm_profile(runtime_profile):
                                await MemoryLearner().learn(
                                    memory_db,
                                    response=memory_response,
                                    deterministic_only=True,
                                )
                            deterministic_memory_projected = True
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "deterministic_memory_projection_failed",
                        response_id=response_id,
                        error=str(exc),
                    )

            next_item = await _next_item_sequence(db, response_id)
            message = ResponseItem(
                id=f"item_{uuid.uuid4().hex}",
                response_id=response_id,
                sequence_number=next_item,
                item_type="message",
                role="assistant",
                content=result.content,
                payload=result.metadata,
            )
            db.add(message)
            response.status = "incomplete" if result.status == "incomplete" else "completed"
            response.model = result.model
            response.completed_at = datetime.now(UTC)
            response.response_metadata = {
                **dict(response.response_metadata or {}),
                **result.metadata,
                "intent": result.intent.to_dict() if result.intent else None,
            }
            await release_lease(db, response)
            await append_event(
                db,
                response_id=response_id,
                event_type="response.output_item.done",
                payload={
                    "item_id": message.id,
                    "item_type": "message",
                    "role": "assistant",
                    "content": result.content,
                },
            )
            final_event = (
                "response.incomplete" if response.status == "incomplete" else "response.completed"
            )
            await append_event(
                db,
                response_id=response_id,
                event_type=final_event,
                payload={
                    "status": response.status,
                    "content": result.content,
                    "model": result.model,
                    "metadata": result.metadata,
                },
            )
            await _persist_model_calls(db, response_id, result.metadata)
            session = await db.get(ChatSession, response.conversation_id)
            if session:
                # Creation/retry already chooses the active branch. A slower
                # older/background response must never rewind a conversation
                # that has since advanced to another response.
                session.turn_count = int(session.turn_count or 0) + 1
                session.last_active = datetime.now(UTC)
            if response.goal_id:
                goal = await db.get(GoalRun, response.goal_id)
                if goal:
                    goal.status = (
                        "completed" if response.status == "completed" else "requires_action"
                    )
                    goal.response_id = response.id
                    goal.current_step = int(goal.current_step or 0) + 1
                    goal.completed_at = datetime.now(UTC)
                    db.add(
                        GoalCheckpoint(
                            id=str(uuid.uuid4()),
                            goal_id=goal.id,
                            step_number=goal.current_step,
                            status="completed",
                            summary=result.content[:2000],
                            state={"response_id": response.id, "model": result.model},
                        )
                    )
            await _update_task_run(
                db,
                response,
                status="incomplete" if response.status == "incomplete" else "succeeded",
                output=result.content,
                finished=True,
            )
            await db.commit()
            attempt_bucket = (
                "1" if response.attempt_count <= 1 else "2" if response.attempt_count == 2 else "3+"
            )
            RESPONSE_COMPLETED_TOTAL.labels(
                status=response.status,
                attempt_bucket=attempt_bucket,
            ).inc()
            if response.created_at and response.completed_at:
                RESPONSE_END_TO_END_DURATION.labels(status=response.status).observe(
                    max(0.0, (response.completed_at - response.created_at).total_seconds())
                )
        try:
            async with AsyncSessionLocal() as summary_db:
                await set_worker_session(summary_db)
                from kernel.agent_loop.summarizer import ConversationSummarizer

                summary_response = await summary_db.get(ResponseRecord, response_id)
                if summary_response:
                    with use_runtime_llm_profile(runtime_profile):
                        await ConversationSummarizer().summarize(
                            summary_db, response=summary_response
                        )
        except Exception as exc:  # noqa: BLE001
            logger.warning("conversation_summary_failed", response_id=response_id, error=str(exc))
        if not deterministic_memory_projected:
            try:
                async with AsyncSessionLocal() as memory_db:
                    await set_worker_session(memory_db)
                    memory_response = await memory_db.get(ResponseRecord, response_id)
                    if memory_response:
                        with use_runtime_llm_profile(runtime_profile):
                            await MemoryLearner().learn(memory_db, response=memory_response)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "response_memory_learning_failed", response_id=response_id, error=str(exc)
                )
        return True
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("response_execution_failed", response_id=response_id, error=str(exc))
        async with AsyncSessionLocal() as db:
            await set_worker_session(db)
            response = await db.get(ResponseRecord, response_id, with_for_update=True)
            if response and response.status not in {"cancelled", "completed", "requires_action"}:
                response.status = (
                    "failed" if response.attempt_count >= response.max_attempts else "queued"
                )
                response.error_code = "response_execution_failed"
                response.error_message = "响应执行失败，请稍后重试。"
                if response.status == "failed":
                    response.completed_at = datetime.now(UTC)
                    await append_event(
                        db,
                        response_id=response_id,
                        event_type="response.failed",
                        payload={
                            "status": "failed",
                            "code": response.error_code,
                            "message": response.error_message,
                        },
                    )
                    if response.goal_id:
                        goal = await db.get(GoalRun, response.goal_id)
                        if goal:
                            goal.status = "failed"
                    await _update_task_run(
                        db,
                        response,
                        status="failed",
                        error=response.error_message,
                        finished=True,
                    )
                else:
                    add_outbox(
                        db, response_id=response_id, suffix=f"retry-{response.attempt_count}"
                    )
                await release_lease(db, response)
                await db.commit()
        return False
    finally:
        tenant_limit.release()
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass


async def _heartbeat(response_id: str) -> None:
    while True:
        await asyncio.sleep(30)
        async with AsyncSessionLocal() as db:
            await set_worker_session(db)
            if not await renew_lease(db, response_id, OWNER):
                return


async def _next_item_sequence(db, response_id: str) -> int:
    from sqlalchemy import func

    current = await db.scalar(
        select(func.max(ResponseItem.sequence_number)).where(
            ResponseItem.response_id == response_id
        )
    )
    return int(current if current is not None else -1) + 1


async def _persist_model_calls(db, response_id: str, metadata: dict) -> None:
    for call in metadata.get("model_calls") or []:
        if not isinstance(call, dict) or not call.get("id"):
            continue
        db.add(
            ResponseModelCall(
                id=f"mcall_{uuid.uuid4().hex}",
                response_id=response_id,
                call_id=str(call["id"]),
                role=str(call.get("role") or "query"),
                model=str(call.get("model") or "") or None,
                latency_ms=int(call["latency_ms"]) if call.get("latency_ms") is not None else None,
                call_metadata={
                    key: value
                    for key, value in call.items()
                    if key not in {"id", "role", "model", "latency_ms"}
                },
            )
        )


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
    if claimed:
        RESPONSE_LEASE_RECOVERY_TOTAL.inc(len(claimed))
    for message_id, fields in claimed:
        data = json.loads(str(fields.get("data") or "{}"))
        await execute_response(str(data.get("response_id") or "") or None)
        await redis.xack(STREAM, GROUP, message_id)
        processed += 1
    return processed


async def _process_stream_message(
    redis, message_id: str, fields: dict, semaphore: asyncio.Semaphore
) -> bool:
    async with semaphore:
        data = json.loads(str(fields.get("data") or "{}"))
        await execute_response(str(data.get("response_id") or "") or None)
        await redis.xack(STREAM, GROUP, message_id)
        return True


async def response_worker_loop() -> None:
    try:
        await _ensure_group()
    except Exception as exc:  # noqa: BLE001
        logger.warning("response_stream_setup_failed_using_db_poll", error=str(exc))
    semaphore = asyncio.Semaphore(max(1, int(settings.response_worker_concurrency)))
    while True:
        try:
            await dispatch_outbox()
            processed = False
            try:
                redis = await get_queue_redis()
                if await _reclaim_pending(redis):
                    processed = True
                rows = await redis.xreadgroup(
                    GROUP,
                    OWNER,
                    streams={STREAM: ">"},
                    count=max(1, int(settings.response_worker_batch_size)),
                    block=1000,
                )
                tasks = [
                    _process_stream_message(redis, message_id, fields, semaphore)
                    for _, entries in rows
                    for message_id, fields in entries
                ]
                if tasks:
                    await asyncio.gather(*tasks)
                    processed = True
            except Exception as exc:  # noqa: BLE001
                logger.debug("response_stream_read_failed", error=str(exc))
            # DB claim is the recovery path for lost Redis messages and Redis outages.
            if not processed:
                await execute_response()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            WORKER_ITERATION_FAILURES_TOTAL.labels(worker_type="responses").inc()
            logger.warning("response_worker_iteration_failed", error=str(exc))
            await asyncio.sleep(1)
