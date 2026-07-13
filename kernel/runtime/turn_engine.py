"""Provider-neutral turn state machine and Responses-style tool loop.

The public API exposes three transports (sync, SSE and background), but they
must not implement three different executions.  ``TurnEngine`` is the small
orchestration boundary shared by those transports.  It keeps lifecycle events
explicit and delegates the actual model/tool work to injected callables, which
also makes the loop deterministic in tests.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, AsyncIterator, Awaitable, Callable

from model.llm_adapter.base import LLMMessage, LLMResponse


class TurnPhase(StrEnum):
    ACCEPTED = "accepted"
    GUARDED = "guarded"
    INTENT_RESOLVED = "intent_resolved"
    CONTEXT_READY = "context_ready"
    MODEL_RUNNING = "model_running"
    TOOL_RUNNING = "tool_running"
    SYNTHESIZING = "synthesizing"
    VALIDATING = "validating"
    PERSISTING = "persisting"
    COMPLETED = "completed"
    REQUIRES_ACTION = "requires_action"
    RETRYING = "retrying"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL = {TurnPhase.COMPLETED, TurnPhase.REQUIRES_ACTION, TurnPhase.INCOMPLETE,
             TurnPhase.FAILED, TurnPhase.CANCELLED}


@dataclass
class TurnEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    sequence_number: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, "data": self.data, "sequence_number": self.sequence_number}


@dataclass
class TurnState:
    turn_id: str = field(default_factory=lambda: f"turn_{uuid.uuid4().hex}")
    phase: TurnPhase = TurnPhase.ACCEPTED
    round: int = 0
    tool_calls: int = 0
    events: list[TurnEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def transition(self, phase: TurnPhase, **data: Any) -> TurnEvent:
        if self.phase in _TERMINAL:
            raise RuntimeError(f"turn_already_terminal:{self.phase.value}")
        self.phase = phase
        event = TurnEvent(type=f"turn.{phase.value}", data={"turn_id": self.turn_id, **data}, sequence_number=len(self.events))
        self.events.append(event)
        return event


Runner = Callable[[TurnState], Awaitable[Any]]


class TurnEngine:
    """Execute one lifecycle for sync and streaming transports."""

    def __init__(self, runner: Runner):
        self.runner = runner

    async def run(self, state: TurnState | None = None) -> tuple[TurnState, Any]:
        state = state or TurnState()
        try:
            for phase in (TurnPhase.GUARDED, TurnPhase.INTENT_RESOLVED, TurnPhase.CONTEXT_READY,
                          TurnPhase.MODEL_RUNNING):
                state.transition(phase)
            result = await self.runner(state)
            state.transition(TurnPhase.SYNTHESIZING)
            state.transition(TurnPhase.VALIDATING)
            state.transition(TurnPhase.PERSISTING)
            state.transition(TurnPhase.COMPLETED)
            return state, result
        except asyncio.CancelledError:
            if state.phase not in _TERMINAL:
                state.transition(TurnPhase.CANCELLED)
            raise
        except Exception as exc:
            if state.phase not in _TERMINAL:
                state.transition(TurnPhase.FAILED, error=str(exc)[:500])
            raise

    async def stream(self, state: TurnState | None = None) -> AsyncIterator[TurnEvent]:
        state = state or TurnState()
        # Emit lifecycle events before executing; the result is represented by
        # the runner's final event when the runner is an async generator.
        try:
            for phase in (TurnPhase.GUARDED, TurnPhase.INTENT_RESOLVED, TurnPhase.CONTEXT_READY,
                          TurnPhase.MODEL_RUNNING):
                yield state.transition(phase)
            if hasattr(self.runner, "stream"):
                async for event in self.runner.stream(state):  # type: ignore[attr-defined]
                    yield event
            else:
                result = await self.runner(state)
                yield TurnEvent("turn.result", {"result": result}, len(state.events))
            for phase in (TurnPhase.SYNTHESIZING, TurnPhase.VALIDATING, TurnPhase.PERSISTING,
                          TurnPhase.COMPLETED):
                yield state.transition(phase)
        except asyncio.CancelledError:
            if state.phase not in _TERMINAL:
                yield state.transition(TurnPhase.CANCELLED)
            raise
        except Exception as exc:
            if state.phase not in _TERMINAL:
                yield state.transition(TurnPhase.FAILED, error=str(exc)[:500])
            raise


def _tool_name(call: dict[str, Any]) -> str:
    return str(call.get("name") or call.get("function", {}).get("name") or "")


def _tool_arguments(call: dict[str, Any]) -> dict[str, Any]:
    raw = call.get("arguments") or call.get("parameters") or call.get("function", {}).get("arguments") or {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


class ResponsesToolLoop:
    """A bounded Responses/function-calling loop over ModelGateway.

    ``complete`` is injected so providers and tests can use the same protocol.
    Tool execution is delegated to the existing schema-validating executor;
    unknown or malformed calls become tool outputs and never crash the turn.
    """

    def __init__(self, model_complete: Callable[..., Awaitable[LLMResponse]], tool_executor: Any,
                 *, max_rounds: int = 8):
        self.model_complete = model_complete
        self.tool_executor = tool_executor
        self.max_rounds = max(1, max_rounds)

    async def run(self, messages: list[LLMMessage], *, tools: list[dict[str, Any]] | None = None,
                  parallel_tool_calls: bool = True, tool_choice: str = "auto",
                  max_output_tokens: int | None = None) -> tuple[LLMResponse, list[dict[str, Any]]]:
        history = list(messages)
        calls_log: list[dict[str, Any]] = []
        for round_no in range(self.max_rounds):
            response = await self.model_complete(
                history,
                tools=tools or [],
                tool_choice=tool_choice,
                parallel_tool_calls=parallel_tool_calls,
                max_output_tokens=max_output_tokens,
            )
            response.raw = {**dict(response.raw or {}), "turn_round": round_no + 1}
            if not response.tool_calls or tool_choice == "none":
                return response, calls_log
            calls = response.tool_calls if parallel_tool_calls else response.tool_calls[:1]
            assistant_calls = [{"id": c.get("id") or c.get("call_id") or f"call_{uuid.uuid4().hex}",
                                "type": "function", "function": {"name": _tool_name(c),
                                "arguments": json.dumps(_tool_arguments(c), ensure_ascii=False)}} for c in calls]
            history.append(LLMMessage(role="assistant", content=response.content or None, tool_calls=assistant_calls))
            results = await self.tool_executor.execute([
                {"name": _tool_name(c), "parameters": _tool_arguments(c)} for c in calls
            ])
            for call, result in zip(calls, results):
                call_id = str(call.get("call_id") or call.get("id") or "")
                payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
                calls_log.append({"call_id": call_id, **payload})
                history.append(LLMMessage(role="tool", name=_tool_name(call), tool_call_id=call_id,
                                          content=json.dumps(payload, ensure_ascii=False, default=str)))
        raise RuntimeError("tool_loop_max_rounds_exceeded")

