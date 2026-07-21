from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from infra.message_bus.cognitive_event_bus import CognitiveEventBus, cognitive_event_bus
from infra.message_bus.events import CognitiveEvent, CognitiveEventType
from infra.observability.logger import get_logger

logger = get_logger(__name__)

EventHandler = Callable[[CognitiveEvent], Awaitable[None]]


@dataclass
class SubscriptionSpec:
    event_type: CognitiveEventType
    handler: EventHandler
    name: str


@dataclass
class SubscriberRuntimeState:
    running: bool = False
    stopping: bool = False
    attempts: int = 0
    backoff_seconds: float = 1.0
    task: asyncio.Task | None = None
    subscriptions: list[SubscriptionSpec] = field(default_factory=list)


class MemoryEventSubscriber:
    def __init__(self, bus: CognitiveEventBus = cognitive_event_bus) -> None:
        self.bus = bus
        from memory.memory_router.router import get_memory_router
        self.router = get_memory_router()
        self._state = SubscriberRuntimeState(
            subscriptions=[
                SubscriptionSpec(CognitiveEventType.FEEDBACK, self._handle_feedback, "feedback"),
                SubscriptionSpec(CognitiveEventType.LEARNING, self._handle_learning, "learning"),
            ]
        )

    @property
    def running(self) -> bool:
        return self._state.running

    @property
    def stopping(self) -> bool:
        return self._state.stopping

    async def start(self) -> None:
        if self._state.running:
            return
        self._state.running = True
        self._state.stopping = False
        self._state.attempts = 0
        self._state.task = asyncio.current_task()
        try:
            await self._run_forever()
        finally:
            self._state.running = False
            self._state.task = None

    async def stop(self) -> None:
        self._state.stopping = True
        task = self._state.task
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(Exception):
                await task

    async def _run_forever(self) -> None:
        while not self._state.stopping:
            try:
                self._state.attempts += 1
                self._state.backoff_seconds = 1.0
                await asyncio.gather(
                    *(self.bus.subscribe(spec.event_type, spec.handler) for spec in self._state.subscriptions)
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "memory event subscriber disconnected",
                    error=str(exc),
                    attempt=self._state.attempts,
                    backoff_seconds=self._state.backoff_seconds,
                )
                await self._sleep_with_backoff()

    async def _sleep_with_backoff(self) -> None:
        delay = min(max(self._state.backoff_seconds, 1.0), 30.0)
        self._state.backoff_seconds = min(delay * 2, 30.0)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise

    async def _handle_feedback(self, event: CognitiveEvent) -> None:
        payload = event.payload or {}
        query = str(payload.get("query") or payload.get("action") or "")
        answer = str(payload.get("answer") or payload.get("response") or "")
        score = float(payload.get("score") or payload.get("validation_score") or 0.7)
        session_id = str(event.session_id or payload.get("session_id") or event.trace_id)
        if not query and not answer:
            return
        await self.router.store(
            session_id=session_id,
            query=query,
            answer=answer,
            metadata={
                "trace_id": event.trace_id,
                "event_type": event.event_type.value,
                "source": event.source,
                "causation_id": event.causation_id,
            },
            score=score,
            success=score >= 0.5,
        )

    async def _handle_learning(self, event: CognitiveEvent) -> None:
        payload = event.payload or {}
        if payload.get("action") == "orchestrator.process.completed":
            query = str(payload.get("query") or event.trace_id)
            answer = str(payload.get("route") or "learning_event")
            await self.router.store(
                session_id=str(event.session_id or event.trace_id),
                query=query,
                answer=answer,
                metadata={"trace_id": event.trace_id, "learning": payload},
                score=float(payload.get("validation_score") or 0.8),
                success=bool(payload.get("passed_validation", True)),
            )


memory_event_subscriber = MemoryEventSubscriber()
