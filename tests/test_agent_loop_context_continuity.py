from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from kernel.agent_loop.contracts import (
    ExecutionPlan,
    ExecutionProfile,
    ExecutionStep,
    SideEffect,
    ToolSpec,
)
from kernel.agent_loop.discovery import CapabilityDiscovery
from kernel.agent_loop.runner import AgentLoop, _normalize_tool_call
from memory.quality import memory_quality_issue
from model.llm_adapter.base import LLMResponse
from services.calendar_intent import parse_calendar_create_intent


def _spec(name: str, description: str, side_effect: SideEffect = SideEffect.READ) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        parameters={"type": "object", "properties": {}},
        side_effect=side_effect,
    )


def test_small_capability_catalogue_excludes_zero_score_tools() -> None:
    result = CapabilityDiscovery(catalogue_limit=48).discover(
        "明天上午帮我记录到日历",
        [
            _spec("create_calendar_event", "创建个人日历日程", SideEffect.WRITE),
            _spec("create_data_alert", "创建企业数据预警", SideEffect.WRITE),
            _spec("get_weather", "查询城市天气"),
        ],
    )

    assert "create_calendar_event" in {item.name for item in result.matches}
    assert "get_weather" not in {item.name for item in result.matches}


def test_short_confirmation_inherits_unfinished_calendar_action() -> None:
    messages = [
        {"role": "system", "content": "平台边界"},
        {"role": "user", "content": "明天上午开发 OpenTrace，帮我记录下来"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-calendar",
                    "type": "function",
                    "function": {
                        "name": "create_calendar_event",
                        "arguments": (
                            '{"title":"开发 OpenTrace",'
                            '"start_at":"2026-07-31T09:50:00+08:00",'
                            '"end_at":"2026-07-31T11:50:00+08:00"}'
                        ),
                    },
                }
            ],
        },
        {"role": "assistant", "content": "请确认是否创建此日程？"},
        {"role": "user", "content": "确认创建"},
    ]
    specs = [
        _spec("create_scheduled_task", "创建定时任务", SideEffect.WRITE),
        _spec("create_data_alert", "创建数据预警", SideEffect.WRITE),
        _spec("create_calendar_event", "创建个人日历日程", SideEffect.WRITE),
    ]

    pending = AgentLoop._pending_action_from_context(
        messages,
        specs,
        current_message_count=1,
    )
    governed = AgentLoop._apply_pending_action_policy(
        "确认创建",
        {"capabilities": ["create_scheduled_task", "create_data_alert"]},
        pending,
    )

    assert pending == {
        "name": "create_calendar_event",
        "call_id": "call-calendar",
        "arguments": {
            "title": "开发 OpenTrace",
            "start_at": "2026-07-31T09:50:00+08:00",
            "end_at": "2026-07-31T11:50:00+08:00",
        },
    }
    assert governed["capabilities"] == ["create_calendar_event"]
    assert governed["steps"][0]["depends_on"] == []


def test_completed_write_tool_is_not_treated_as_pending_action() -> None:
    messages = [
        {"role": "system", "content": "平台边界"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call-calendar",
                    "function": {"name": "create_calendar_event", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-calendar", "content": "成功"},
        {"role": "user", "content": "确认"},
    ]

    assert (
        AgentLoop._pending_action_from_context(
            messages,
            [_spec("create_calendar_event", "创建日程", SideEffect.WRITE)],
            current_message_count=1,
        )
        is None
    )


def test_tool_arguments_are_schema_normalized_and_internal_scope_is_removed() -> None:
    normalized = _normalize_tool_call(
        {
            "id": "call-calendar",
            "function": {
                "name": "create_calendar_event",
                "arguments": {
                    "title": "开发 OpenTrace",
                    "all_day": "False",
                    "reminder_minutes": "[10]",
                    "response_id": "model-forged-response",
                    "tenant_id": "model-forged-tenant",
                },
            },
        },
        ToolSpec(
            name="create_calendar_event",
            description="创建日程",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "all_day": {"type": "boolean"},
                    "reminder_minutes": {"type": "array", "items": {"type": "integer"}},
                },
            },
            side_effect=SideEffect.WRITE,
        ),
    )

    assert normalized["arguments"] == {
        "title": "开发 OpenTrace",
        "all_day": False,
        "reminder_minutes": [10],
    }


def test_pending_write_guard_only_forces_unfinished_side_effect_steps() -> None:
    plan = ExecutionPlan(
        goal="记录日程",
        steps=(
            ExecutionStep("read", "查询冲突", "list_calendar_events"),
            ExecutionStep("write", "创建日程", "create_calendar_event"),
        ),
    )
    pending = AgentLoop._pending_write_capabilities(
        plan,
        {"read": "completed", "write": "pending"},
        {
            "list_calendar_events": _spec("list_calendar_events", "查询日历"),
            "create_calendar_event": _spec(
                "create_calendar_event",
                "创建日程",
                SideEffect.WRITE,
            ),
        },
    )

    assert pending == {"create_calendar_event"}


def test_read_only_calendar_question_cannot_expand_into_write_intent() -> None:
    specs = [
        _spec("list_calendar_events", "查询日历"),
        _spec("create_calendar_event", "创建日程", SideEffect.WRITE),
    ]
    governed = AgentLoop._apply_side_effect_intent_policy(
        "我明天上午安排了什么？",
        {
            "capabilities": ["list_calendar_events", "create_calendar_event"],
            "steps": [
                {"id": "read", "capability": "list_calendar_events"},
                {"id": "write", "capability": "create_calendar_event"},
            ],
        },
        specs,
        None,
    )

    assert AgentLoop._is_explicit_write_request("我明天上午安排了什么？") is False
    assert AgentLoop._is_explicit_write_request("帮我记录到日历") is True
    assert governed["capabilities"] == ["list_calendar_events"]
    assert [step["id"] for step in governed["steps"]] == ["read"]


def test_confirming_pending_action_remains_an_explicit_write_request() -> None:
    pending = {"name": "create_calendar_event", "arguments": {"title": "开发 OpenTrace"}}

    assert AgentLoop._is_explicit_write_request("确认创建", pending_action=pending) is True


def test_explicit_calendar_request_is_deterministically_prepared_for_approval() -> None:
    parsed = parse_calendar_create_intent(
        "我明天上午要开发OpenTrace，上午9:50-11:50，帮我记录下来",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed == {
        "title": "开发 OpenTrace",
        "start_at": "2026-07-31T09:50:00+08:00",
        "end_at": "2026-07-31T11:50:00+08:00",
        "timezone": "Asia/Shanghai",
        "description": "开发 OpenTrace",
        "location": "",
        "event_type": "focus",
        "all_day": False,
        "recurrence_rule": "",
        "reminder_minutes": [15],
    }


def test_deterministic_calendar_call_is_stable_and_schema_scoped(monkeypatch) -> None:
    monkeypatch.setattr(
        "kernel.agent_loop.runner.parse_calendar_create_intent",
        lambda *args, **kwargs: {
            "title": "开发 OpenTrace",
            "start_at": "2026-07-31T09:50:00+08:00",
            "end_at": "2026-07-31T11:50:00+08:00",
            "all_day": False,
        },
    )
    spec = ToolSpec(
        name="create_calendar_event",
        description="创建日程",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_at": {"type": "string"},
                "end_at": {"type": "string"},
                "all_day": {"type": "boolean"},
            },
        },
        side_effect=SideEffect.WRITE,
    )

    prepared = AgentLoop._deterministic_write_call(
        query="帮我记录到日历",
        response=SimpleNamespace(id="resp-1"),
        extension={"timezone": "Asia/Shanghai"},
        tool_specs=[spec],
        pending_action=None,
    )

    assert prepared is not None
    call, selected_spec = prepared
    assert selected_spec is spec
    assert call["call_id"].startswith("call_deterministic_")
    assert call["arguments"]["all_day"] is False


@pytest.mark.asyncio
async def test_default_plan_does_not_invent_capability_dependencies(monkeypatch) -> None:
    class FakeGateway:
        async def complete(self, *args, **kwargs):
            return LLMResponse(
                content="",
                model="planner",
                tool_calls=[
                    {
                        "id": "plan-call",
                        "type": "function",
                        "function": {
                            "name": "emit_intent_plan",
                            "arguments": {
                                "goal": "创建日程",
                                "task_type": "chat",
                                "capabilities": [
                                    "list_calendar_events",
                                    "create_calendar_event",
                                ],
                                "ambiguity": None,
                                "execution_mode": "interactive",
                                "expected_outputs": ["answer"],
                                "clarification_question": None,
                                "complexity": "simple",
                                "steps": [],
                                "success_criteria": ["日程进入审批"],
                                "replan_limit": 1,
                            },
                        },
                    }
                ],
            )

    monkeypatch.setattr("kernel.agent_loop.runner.get_model_gateway", lambda: FakeGateway())
    decision = await AgentLoop()._plan_turn(
        query="帮我记录到日历",
        attachment_context="",
        profile=ExecutionProfile.AUTO,
        tool_specs=[
            _spec("list_calendar_events", "查询个人日历"),
            _spec("create_calendar_event", "创建个人日历日程", SideEffect.WRITE),
        ],
        goal_mode=False,
        capability_catalogue=[],
    )

    assert [step.capability for step in decision.execution_plan.steps] == [
        "list_calendar_events",
        "create_calendar_event",
    ]
    assert all(step.depends_on == () for step in decision.execution_plan.steps)


@pytest.mark.asyncio
async def test_unexecuted_plan_steps_are_skipped_instead_of_completed() -> None:
    events: list[tuple[str, dict]] = []

    async def emit(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    statuses = {"step-1": "pending"}
    await AgentLoop._complete_remaining_plan(
        emit,
        ExecutionPlan(
            goal="创建日程",
            steps=(ExecutionStep("step-1", "创建日程", "create_calendar_event"),),
        ),
        statuses,
    )

    assert statuses == {"step-1": "skipped"}
    assert events[0][0] == "opentrace.plan.step.skipped"


def test_legacy_assistant_identity_transcript_is_quarantined() -> None:
    issue = memory_quality_issue(
        "Q: 你好，请用一句话介绍你自己\n"
        "A: 我是OpenTrace，由Cognitive Kernel驱动的智能认知助手。",
        kind="fact",
        memory_key=None,
        source_response_id=None,
    )

    assert issue == "legacy_assistant_identity_transcript"
    assert (
        memory_quality_issue(
            "我的常用技术栈是 Python 和 React",
            kind="fact",
            memory_key="profile.tech_stack",
            source_response_id="resp-1",
        )
        is None
    )


def test_memory_quality_cleanup_migration_is_governed_and_reversible() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "alembic/versions/r0008_memory_quality_cleanup.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "r0008_memory_quality_cleanup"' in source
    assert 'down_revision = "r0007_enterprise_cognition"' in source
    assert "legacy_assistant_transcript" in source
    assert "SET enabled = false" in source
    assert "SET enabled = true" in source
