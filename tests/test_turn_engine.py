import pytest

from kernel.runtime.turn_engine import ResponsesToolLoop, TurnEngine, TurnPhase, TurnState
from kernel.tools.function_calling.executor import ToolExecutor
from model.llm_adapter.base import LLMResponse


@pytest.mark.asyncio
async def test_turn_engine_emits_one_terminal_lifecycle():
    async def runner(state):
        state.metadata["ran"] = True
        return "ok"

    state, result = await TurnEngine(runner).run()
    assert result == "ok"
    assert state.phase == TurnPhase.COMPLETED
    assert [event.type for event in state.events][-1] == "turn.completed"
    assert [event.sequence_number for event in state.events] == list(range(len(state.events)))


@pytest.mark.asyncio
async def test_responses_tool_loop_executes_calls_and_synthesizes():
    executor = ToolExecutor(timeout_seconds=1)
    executor.register_tool(
        "lookup", lambda key: {"value": key.upper()},
        parameters={"type": "object", "properties": {"key": {"type": "string"}}},
        required=["key"],
    )
    responses = [
        LLMResponse(content="", model="test", tool_calls=[{"id": "call_1", "name": "lookup", "arguments": '{"key":"x"}'}]),
        LLMResponse(content="The value is X", model="test"),
    ]

    async def complete(messages, **kwargs):
        return responses.pop(0)

    result, log = await ResponsesToolLoop(complete, executor).run(
        [], tools=[{"type": "function", "name": "lookup"}],
    )
    assert result.content == "The value is X"
    assert len(log) == 1
    assert log[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_responses_tool_loop_honors_serial_tool_mode():
    executor = ToolExecutor(timeout_seconds=1)
    seen = []
    executor.register_tool("a", lambda: seen.append("a") or 1)
    executor.register_tool("b", lambda: seen.append("b") or 2)
    responses = [LLMResponse(content="", model="test", tool_calls=[
        {"id": "a", "name": "a", "arguments": "{}"},
        {"id": "b", "name": "b", "arguments": "{}"},
    ]), LLMResponse(content="done", model="test")]

    async def complete(messages, **kwargs):
        return responses.pop(0)

    result, log = await ResponsesToolLoop(complete, executor).run([], parallel_tool_calls=False)
    assert result.content == "done"
    assert seen == ["a"]
    assert len(log) == 1
