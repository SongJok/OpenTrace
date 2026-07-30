from types import SimpleNamespace

import pytest

from kernel.agent_loop.context import AssembledContext
from kernel.agent_loop.contracts import (
    ExecutionPlan,
    ExecutionProfile,
    ExecutionStep,
    IntentPlan,
    PlanningDecision,
    SideEffect,
    ToolSpec,
)
from kernel.agent_loop.runner import (
    AgentLoop,
    _LoopProgressTracker,
    _normalize_direct_tool_result,
)
from model.llm_adapter.base import LLMResponse


def _call(call_id: str, query: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "web_search", "arguments": {"query": query}},
    }


def test_progress_tracker_stops_repeated_calls_after_two_stalled_rounds():
    tracker = _LoopProgressTracker()
    success = {"status": "success", "content": "可靠证据"}

    assert tracker.observe([_call("c1", "A 股")], [success]) is None
    assert tracker.observe([_call("c2", "A 股")], [success]) == "repeated_tool_calls"
    assert tracker.should_stop is False
    assert tracker.observe([_call("c3", "A 股")], [success]) == "repeated_tool_calls"
    assert tracker.should_stop is True


def test_progress_tracker_stops_different_failed_calls_and_resets_on_new_evidence():
    tracker = _LoopProgressTracker()
    failed = {"status": "failed", "error": "provider unavailable"}

    assert tracker.observe([_call("c1", "A 股")], [failed]) == "tool_failures"
    assert tracker.consecutive_stalls == 1
    assert (
        tracker.observe(
            [_call("c2", "A 股实时行情")],
            [{"status": "success", "content": "新的可靠证据"}],
        )
        is None
    )
    assert tracker.consecutive_stalls == 0
    assert tracker.observe([_call("c3", "A 股资金")], [failed]) == "tool_failures"
    assert tracker.observe([_call("c4", "A 股成交")], [failed]) == "tool_failures"
    assert tracker.should_stop is True


def test_direct_tool_embedded_error_is_promoted_to_failure():
    unavailable = _normalize_direct_tool_result(
        {
            "status": "completed",
            "result": "Web search unavailable: SERPER_API_KEY not configured.",
        }
    )
    structured = _normalize_direct_tool_result(
        {
            "status": "completed",
            "result": {"status": "failed", "error": "upstream timeout"},
        }
    )
    valid = _normalize_direct_tool_result(
        {"status": "completed", "result": '{"items":[{"title":"A"}]}'},
    )

    assert unavailable["status"] == "failed"
    assert "SERPER_API_KEY" in unavailable["error"]
    assert structured["status"] == "failed"
    assert structured["error"] == "upstream timeout"
    assert valid["status"] == "completed"


@pytest.mark.asyncio
async def test_approved_deterministic_calendar_completion_skips_model(monkeypatch):
    spec = ToolSpec(
        name="create_calendar_event",
        description="创建个人日历日程",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_at": {"type": "string"},
                "end_at": {"type": "string"},
                "timezone": {"type": "string"},
                "reminder_minutes": {"type": "array", "items": {"type": "integer"}},
            },
        },
        side_effect=SideEffect.WRITE,
    )
    intent = IntentPlan(
        goal="创建日程",
        capabilities=("create_calendar_event",),
        risk=SideEffect.WRITE,
    )
    plan = ExecutionPlan(
        goal=intent.goal,
        steps=(ExecutionStep("step-calendar", "创建日程", "create_calendar_event"),),
    )
    context = AssembledContext(
        messages=[
            {"role": "system", "content": "系统指令"},
            {"role": "user", "content": "明天上午开发 OpenTrace，帮我记录下来"},
        ],
        memory_ids=[],
        attachment_ids=[],
        attachment_context="",
        contains_images=False,
        project_id=None,
        assistant_profile_id=None,
        profile_execution_default="auto",
        tool_policy={},
        memory_policy={},
        modality_counts={"text": 1, "image": 0, "audio": 0, "video": 0},
        context_manifest={"estimated_input_tokens": 10, "max_input_tokens": 100_000},
    )
    arguments = {
        "title": "开发 OpenTrace",
        "start_at": "2026-07-31T09:50:00+08:00",
        "end_at": "2026-07-31T11:50:00+08:00",
        "timezone": "Asia/Shanghai",
        "reminder_minutes": [15],
    }
    approval = SimpleNamespace(
        id="approval-calendar",
        status="approved",
        call_id="call_deterministic_calendar",
        tool_name="create_calendar_event",
        arguments=arguments,
    )

    class FakeContextAssembler:
        async def assemble(self, *args, **kwargs):
            return context

    class FakeDB:
        async def scalar(self, *args, **kwargs):
            return approval

        async def flush(self):
            return None

    class FailIfCalledGateway:
        async def complete(self, *args, **kwargs):
            raise AssertionError("审批后的确定性日历回执不应调用模型")

    loop = AgentLoop(context_assembler=FakeContextAssembler())
    response = SimpleNamespace(
        id="response-calendar",
        status="in_progress",
        response_metadata={},
        request_payload={
            "input": "明天上午开发 OpenTrace，帮我记录下来",
            "opentrace": {"timezone": "Asia/Shanghai"},
        },
    )
    events = []

    async def emit(event_type, payload):
        events.append((event_type, payload))

    async def restore_decision(*args, **kwargs):
        return PlanningDecision(intent=intent, execution_plan=plan)

    async def restore_plan(*args, **kwargs):
        return kwargs["proposed"]

    async def plan_runtime(*args, **kwargs):
        return {"step-calendar": "requires_action"}, 0

    async def no_op(*args, **kwargs):
        return None

    async def restore_tools(*args, **kwargs):
        return [
            (
                "create_calendar_event",
                {
                    "status": "completed",
                    "parameters": arguments,
                    "result": {
                        "status": "success",
                        "event": {"title": "开发 OpenTrace"},
                    },
                },
            )
        ]

    monkeypatch.setattr(loop, "_available_tool_specs", lambda payload: [spec])
    monkeypatch.setattr(loop, "_existing_deterministic_approval", no_op)
    monkeypatch.setattr(loop, "_restore_planning_decision", restore_decision)
    monkeypatch.setattr(loop, "_restore_or_persist_execution_plan", restore_plan)
    monkeypatch.setattr(loop, "_execution_plan_runtime", plan_runtime)
    monkeypatch.setattr(loop, "_persist_execution_plan_runtime", no_op)
    monkeypatch.setattr(loop, "_restore_tool_history", restore_tools)
    monkeypatch.setattr("kernel.agent_loop.runner.get_model_gateway", FailIfCalledGateway)

    async def existing_approval(*args, **kwargs):
        return approval

    monkeypatch.setattr(loop, "_existing_deterministic_approval", existing_approval)

    result = await loop.run(FakeDB(), response=response, emit=emit)

    assert result.status == "completed"
    assert result.model == "opentrace-calendar-projection"
    assert "已记录" in result.content
    assert result.metadata["calendar_action_completed"] is True
    assert any(event_type == "response.output_text.done" for event_type, _ in events)


@pytest.mark.asyncio
async def test_agent_loop_finalizes_without_tools_after_two_no_progress_rounds(monkeypatch):
    spec = ToolSpec(
        name="web_search",
        description="查询实时网页信息",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        side_effect=SideEffect.READ,
    )
    intent = IntentPlan(
        goal="查询今日 A 股信息",
        capabilities=("web_search",),
        execution_profile=ExecutionProfile.AUTO,
    )
    plan = ExecutionPlan(
        goal=intent.goal,
        steps=(ExecutionStep("step_1", "查询实时数据", "web_search"),),
        replan_limit=0,
    )
    context = AssembledContext(
        messages=[
            {"role": "system", "content": "系统指令"},
            {"role": "user", "content": "给出今日 A 股信息"},
        ],
        memory_ids=[],
        attachment_ids=[],
        attachment_context="",
        contains_images=False,
        project_id=None,
        assistant_profile_id=None,
        profile_execution_default="auto",
        tool_policy={},
        memory_policy={},
        modality_counts={"text": 1, "image": 0, "audio": 0, "video": 0},
        context_manifest={"estimated_input_tokens": 10, "max_input_tokens": 100_000},
    )

    class FakeContextAssembler:
        async def assemble(self, *args, **kwargs):
            return context

    class FakeDB:
        def __init__(self):
            self.added = []

        async def refresh(self, response):
            return None

        def add(self, item):
            self.added.append(item)

    class FakeGateway:
        def __init__(self):
            self.calls = 0

        async def complete(self, messages, **kwargs):
            self.calls += 1
            if self.calls <= 2:
                return LLMResponse(
                    content="",
                    model="test-model",
                    tool_calls=[_call(f"call-{self.calls}", "今日 A 股信息")],
                )
            assert kwargs["tools"] == []
            assert kwargs["tool_choice"] == "none"
            return LLMResponse(
                content="当前实时数据源不可用，无法可靠给出今日 A 股数据。",
                model="test-model",
            )

    gateway = FakeGateway()
    loop = AgentLoop(max_rounds=8, context_assembler=FakeContextAssembler())
    response = SimpleNamespace(
        id="response-1",
        conversation_id="conversation-1",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        status="in_progress",
        request_payload={"input": "给出今日 A 股信息"},
    )
    events = []

    async def emit(event_type, payload):
        events.append((event_type, payload))

    async def restore_decision(*args, **kwargs):
        return PlanningDecision(intent=intent, execution_plan=plan)

    async def restore_plan(*args, **kwargs):
        return kwargs["proposed"]

    async def plan_runtime(*args, **kwargs):
        return {"step_1": "pending"}, 0

    async def no_op(*args, **kwargs):
        return None

    async def restore_tools(*args, **kwargs):
        return []

    async def next_sequence(*args, **kwargs):
        return 1

    async def execute_tools(*args, **kwargs):
        return [
            {"status": "failed", "error": "SERPER_API_KEY not configured"} for _ in kwargs["calls"]
        ]

    monkeypatch.setattr(loop, "_restore_planning_decision", restore_decision)
    monkeypatch.setattr(loop, "_restore_or_persist_execution_plan", restore_plan)
    monkeypatch.setattr(loop, "_execution_plan_runtime", plan_runtime)
    monkeypatch.setattr(loop, "_persist_execution_plan_runtime", no_op)
    monkeypatch.setattr(loop, "_restore_tool_history", restore_tools)
    monkeypatch.setattr(loop, "_next_item_sequence", next_sequence)
    monkeypatch.setattr(loop, "_execute_tools", execute_tools)
    monkeypatch.setattr(loop, "_available_tool_specs", lambda payload: [spec])
    monkeypatch.setattr("kernel.agent_loop.runner.get_model_gateway", lambda: gateway)

    result = await loop.run(FakeDB(), response=response, emit=emit)

    assert result.status == "completed"
    assert "实时数据源不可用" in result.content
    assert result.metadata["loop_termination"]["reason"] == "tool_loop_no_progress"
    assert result.metadata["loop_termination"]["consecutive_rounds"] == 2
    assert gateway.calls == 3
    assert any(event_type == "opentrace.loop.no_progress" for event_type, _ in events)
    assert not any("步骤上限" in payload.get("text", "") for _, payload in events)
