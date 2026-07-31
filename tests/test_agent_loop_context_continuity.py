from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from kernel.agent_loop.calendar_planning import deterministic_calendar_completion
from kernel.agent_loop.contracts import (
    ExecutionPlan,
    ExecutionProfile,
    ExecutionStep,
    IntentPlan,
    PlanningDecision,
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
    assert AgentLoop._is_explicit_write_request("帮我记录一下") is True
    assert AgentLoop._is_explicit_write_request("帮我新增到日历") is True
    assert (
        AgentLoop._is_explicit_write_request("帮我预定：明天下午两点到三点的日历，名称：开发会议")
        is True
    )
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


def test_calendar_booking_with_explicit_name_uses_beijing_time() -> None:
    parsed = parse_calendar_create_intent(
        "帮我预定：明天下午两点到三点的日历，名称：开发会议",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 31, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is not None
    assert parsed["title"] == "开发会议"
    assert parsed["start_at"] == "2026-08-01T14:00:00+08:00"
    assert parsed["end_at"] == "2026-08-01T15:00:00+08:00"
    assert parsed["timezone"] == "Asia/Shanghai"
    assert parsed["event_type"] == "meeting"


def test_non_calendar_booking_is_not_captured_as_calendar_write() -> None:
    parsed = parse_calendar_create_intent(
        "帮我预定明天下午两点到三点的酒店",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 31, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is None


def test_single_chinese_calendar_time_defaults_to_one_hour() -> None:
    parsed = parse_calendar_create_intent(
        "明天下午三点客户复盘，帮我记录到日历",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is not None
    assert parsed["title"] == "客户复盘"
    assert parsed["start_at"] == "2026-07-31T15:00:00+08:00"
    assert parsed["end_at"] == "2026-07-31T16:00:00+08:00"


@pytest.mark.parametrize(
    "query",
    [
        "明天下午三点提醒我检查数据",
        "请明天下午三点提醒我检查数据",
    ],
)
def test_calendar_reminder_preserves_the_requested_title(query: str) -> None:
    parsed = parse_calendar_create_intent(
        query,
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is not None
    assert parsed["title"] == "检查数据"
    assert parsed["start_at"] == "2026-07-31T15:00:00+08:00"
    assert parsed["end_at"] == "2026-07-31T16:00:00+08:00"


def test_calendar_reminder_preserves_title_after_time_clause() -> None:
    parsed = parse_calendar_create_intent(
        "明天下午三点，提醒我检查数据",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is not None
    assert parsed["title"] == "检查数据"


def test_calendar_early_midnight_is_not_parsed_as_noon() -> None:
    parsed = parse_calendar_create_intent(
        "明天凌晨十二点提醒我发布版本",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is not None
    assert parsed["start_at"] == "2026-07-31T00:00:00+08:00"
    assert parsed["end_at"] == "2026-07-31T01:00:00+08:00"


def test_calendar_noon_and_end_of_day_midnight_use_expected_dates() -> None:
    now = datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    noon = parse_calendar_create_intent(
        "明天上午十二点提醒我午间发布",
        timezone_name="Asia/Shanghai",
        now=now,
    )
    end_of_day = parse_calendar_create_intent(
        "明天晚上十二点提醒我夜间发布",
        timezone_name="Asia/Shanghai",
        now=now,
    )

    assert noon is not None
    assert noon["start_at"] == "2026-07-31T12:00:00+08:00"
    assert end_of_day is not None
    assert end_of_day["start_at"] == "2026-08-01T00:00:00+08:00"


def test_calendar_time_range_can_cross_midnight() -> None:
    parsed = parse_calendar_create_intent(
        "明天晚上十一点到凌晨一点值班，帮我记录到日历",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is not None
    assert parsed["title"] == "值班"
    assert parsed["start_at"] == "2026-07-31T23:00:00+08:00"
    assert parsed["end_at"] == "2026-08-01T01:00:00+08:00"


def test_chinese_calendar_time_range_is_not_reduced_to_single_hour() -> None:
    parsed = parse_calendar_create_intent(
        "明天下午三点半到五点客户复盘，帮我记录到日历",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is not None
    assert parsed["start_at"] == "2026-07-31T15:30:00+08:00"
    assert parsed["end_at"] == "2026-07-31T17:00:00+08:00"


def test_calendar_time_without_date_remains_ambiguous() -> None:
    parsed = parse_calendar_create_intent(
        "下午三点客户复盘，帮我记录到日历",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is None


def test_calendar_parser_requires_calendar_specific_write_intent() -> None:
    parsed = parse_calendar_create_intent(
        "明天下午三点创建数据预警，帮我记录下来",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is None


def test_calendar_parser_requires_an_explicit_calendar_write_marker() -> None:
    parsed = parse_calendar_create_intent(
        "明天下午三点客户复盘",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is None


def test_read_only_calendar_question_is_not_parsed_as_write() -> None:
    parsed = parse_calendar_create_intent(
        "明天上午九点日历里有什么安排",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is None


@pytest.mark.parametrize(
    "title",
    ["监控系统评审会", "工单流程复盘", "审批规则评审", "待办功能验收"],
)
def test_business_terms_in_calendar_title_are_not_treated_as_competing_intents(
    title: str,
) -> None:
    parsed = parse_calendar_create_intent(
        f"明天下午三点{title}，帮我记录到日历",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is not None
    assert parsed["title"] == title


def test_calendar_parser_does_not_capture_scheduled_task_request() -> None:
    parsed = parse_calendar_create_intent(
        "明天下午三点创建定时任务，帮我记录到日历",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is None


def test_calendar_date_without_year_rolls_forward_across_new_year() -> None:
    parsed = parse_calendar_create_intent(
        "1月2日上午九点年度启动会，帮我记录到日历",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 12, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is not None
    assert parsed["start_at"] == "2027-01-02T09:00:00+08:00"


def test_compact_english_calendar_write_marker_is_reachable() -> None:
    parsed = parse_calendar_create_intent(
        "明天下午三点发布评审，create event",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is not None
    assert parsed["title"] == "发布评审"


@pytest.mark.parametrize(
    "marker",
    ["记录一下", "记一下", "新增到日历", "创建日历事件"],
)
def test_common_calendar_write_markers_are_supported(marker: str) -> None:
    parsed = parse_calendar_create_intent(
        f"明天下午三点客户复盘，帮我{marker}",
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 7, 30, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert parsed is not None
    assert parsed["title"] == "客户复盘"


def test_deterministic_calendar_call_is_stable_and_schema_scoped(monkeypatch) -> None:
    monkeypatch.setattr(
        "kernel.agent_loop.calendar_planning.parse_calendar_create_intent",
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


def test_deterministic_calendar_call_anchors_relative_date_to_response_creation(
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_parse(*args, **kwargs):
        observed.update(kwargs)
        return {
            "title": "开发 OpenTrace",
            "start_at": "2026-07-31T09:50:00+08:00",
            "end_at": "2026-07-31T11:50:00+08:00",
        }

    monkeypatch.setattr(
        "kernel.agent_loop.calendar_planning.parse_calendar_create_intent", fake_parse
    )
    created_at = datetime(2026, 7, 30, 15, 59, tzinfo=ZoneInfo("UTC"))

    prepared = AgentLoop._deterministic_write_call(
        query="我明天上午要开发OpenTrace，上午9:50-11:50，帮我记录下来",
        response=SimpleNamespace(id="resp-midnight", created_at=created_at),
        extension={"timezone": "Asia/Shanghai"},
        tool_specs=[_spec("create_calendar_event", "创建日程", SideEffect.WRITE)],
        pending_action=None,
    )

    assert prepared is not None
    assert observed["now"] == created_at


def test_deterministic_calendar_call_keeps_same_date_across_midnight() -> None:
    spec = ToolSpec(
        name="create_calendar_event",
        description="创建日程",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_at": {"type": "string"},
                "end_at": {"type": "string"},
                "timezone": {"type": "string"},
            },
        },
        side_effect=SideEffect.WRITE,
    )
    response = SimpleNamespace(
        id="resp-midnight",
        created_at=datetime(2026, 7, 30, 15, 59, tzinfo=ZoneInfo("UTC")),
    )

    prepared = AgentLoop._deterministic_write_call(
        query="我明天上午要开发OpenTrace，上午9:50-11:50，帮我记录下来",
        response=response,
        extension={"timezone": "Asia/Shanghai"},
        tool_specs=[spec],
        pending_action=None,
    )

    assert prepared is not None
    assert prepared[0]["arguments"]["start_at"] == "2026-07-31T09:50:00+08:00"


def test_deterministic_calendar_recovery_reuses_existing_approval() -> None:
    spec = ToolSpec(
        name="create_calendar_event",
        description="创建日程",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_at": {"type": "string"},
                "end_at": {"type": "string"},
            },
        },
        side_effect=SideEffect.WRITE,
    )
    stored_arguments = {
        "title": "开发 OpenTrace",
        "start_at": "2026-07-31T09:50:00+08:00",
        "end_at": "2026-07-31T11:50:00+08:00",
    }
    approval = SimpleNamespace(
        call_id="call_deterministic_existing",
        tool_name="create_calendar_event",
        arguments=stored_arguments,
    )

    prepared = AgentLoop._deterministic_write_call(
        query="我明天上午要开发OpenTrace，上午9:50-11:50，帮我记录下来",
        response=SimpleNamespace(
            id="resp-midnight",
            created_at=datetime(2026, 7, 31, 16, 1, tzinfo=ZoneInfo("UTC")),
        ),
        extension={"timezone": "Asia/Shanghai"},
        tool_specs=[spec],
        pending_action=None,
        calendar_arguments={
            "title": "错误的新日期",
            "start_at": "2026-08-02T09:50:00+08:00",
            "end_at": "2026-08-02T11:50:00+08:00",
        },
        existing_approval=approval,
    )

    assert prepared is not None
    assert prepared[0]["call_id"] == approval.call_id
    assert prepared[0]["arguments"] == stored_arguments


def test_deterministic_calendar_supplements_planner_omission() -> None:
    decision = PlanningDecision(
        intent=IntentPlan(
            goal="记录日程",
            capabilities=("list_calendar_events",),
            execution_profile=ExecutionProfile.AUTO,
        ),
        execution_plan=ExecutionPlan(
            goal="记录日程",
            steps=(ExecutionStep("read", "查询日历", "list_calendar_events"),),
        ),
    )
    spec = _spec("create_calendar_event", "创建个人日历日程", SideEffect.WRITE)

    supplemented = AgentLoop._supplement_deterministic_calendar_decision(
        decision,
        spec=spec,
    )

    assert supplemented.intent.capabilities == ("create_calendar_event",)
    assert supplemented.intent.risk == SideEffect.WRITE
    assert [step.capability for step in supplemented.execution_plan.steps] == [
        "create_calendar_event",
    ]


def test_deterministic_calendar_completion_does_not_require_model() -> None:
    approval = SimpleNamespace(
        status="approved",
        call_id="call_deterministic_calendar",
        tool_name="create_calendar_event",
        arguments={
            "title": "开发 OpenTrace",
            "start_at": "2026-07-31T09:50:00+08:00",
            "end_at": "2026-07-31T11:50:00+08:00",
            "timezone": "Asia/Shanghai",
            "reminder_minutes": [15],
        },
    )

    content = deterministic_calendar_completion(
        approval=approval,
        restored_tools=[
            (
                "create_calendar_event",
                {
                    "status": "completed",
                    "result": {
                        "status": "success",
                        "event": {"title": "开发 OpenTrace"},
                    },
                },
            )
        ],
    )

    assert content is not None
    assert "已记录" in content
    assert "2026年7月31日 09:50–11:50" in content
    assert "提前 15 分钟" in content
    assert "[查看我的日历](/calendar)" in content


def test_deterministic_calendar_respects_denied_tool_policy() -> None:
    specs = AgentLoop._apply_tool_policy(
        [_spec("create_calendar_event", "创建日程", SideEffect.WRITE)],
        {"denied_tools": ["create_calendar_event"]},
    )

    arguments = AgentLoop._deterministic_calendar_arguments(
        query="明天下午三点客户复盘，帮我记录到日历",
        response=SimpleNamespace(
            id="resp-denied",
            created_at=datetime(2026, 7, 30, 3, 0, tzinfo=ZoneInfo("UTC")),
        ),
        extension={"timezone": "Asia/Shanghai"},
        tool_specs=specs,
    )

    assert arguments is None


def test_deterministic_calendar_requires_write_enabled_tool() -> None:
    arguments = AgentLoop._deterministic_calendar_arguments(
        query="明天下午三点客户复盘，帮我记录到日历",
        response=SimpleNamespace(
            id="resp-read-only",
            created_at=datetime(2026, 7, 30, 3, 0, tzinfo=ZoneInfo("UTC")),
        ),
        extension={"timezone": "Asia/Shanghai"},
        tool_specs=[_spec("create_calendar_event", "创建日程", SideEffect.READ)],
    )

    assert arguments is None


@pytest.mark.asyncio
async def test_agent_loop_prepares_calendar_approval_when_planner_omits_tool(
    monkeypatch,
) -> None:
    query = "帮我预定：明天下午两点到三点的日历，名称：开发会议"
    context = SimpleNamespace(
        messages=[
            {"role": "system", "content": "系统指令"},
            {"role": "user", "content": query},
        ],
        current_message_count=1,
        attachment_context="",
        profile_execution_default="auto",
        tool_policy={},
        memory_policy={},
        memory_ids=[],
        attachment_ids=[],
        project_id=None,
        assistant_profile_id=None,
        modality_counts={"text": 1, "image": 0, "audio": 0, "video": 0},
        context_manifest={"estimated_input_tokens": 10, "max_input_tokens": 100_000},
    )

    class FakeContextAssembler:
        async def assemble(self, *args, **kwargs):
            return context

    class FakeDB:
        def __init__(self):
            self.added = []

        async def scalar(self, *args, **kwargs):
            return None

        async def flush(self):
            return None

        async def commit(self):
            return None

        def add(self, item):
            self.added.append(item)

    calendar_spec = ToolSpec(
        name="create_calendar_event",
        description="创建日程",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_at": {"type": "string"},
                "end_at": {"type": "string"},
                "timezone": {"type": "string"},
                "event_type": {"type": "string"},
            },
        },
        side_effect=SideEffect.WRITE,
    )
    planner_decision = PlanningDecision(
        intent=IntentPlan(goal="回复用户"),
        execution_plan=ExecutionPlan(
            goal="回复用户",
            steps=(ExecutionStep("answer", "直接回复用户"),),
        ),
    )
    response = SimpleNamespace(
        id="resp-planner-omission",
        status="in_progress",
        response_metadata={},
        request_payload={"input": query, "opentrace": {}},
        created_at=datetime(2026, 7, 31, 2, 0, tzinfo=ZoneInfo("UTC")),
    )
    approval_calls: list[dict] = []
    events: list[tuple[str, dict]] = []
    loop = AgentLoop(context_assembler=FakeContextAssembler())

    async def restore_decision(*args, **kwargs):
        return planner_decision

    async def restore_plan(*args, **kwargs):
        return kwargs["proposed"]

    async def plan_runtime(*args, **kwargs):
        plan = kwargs["plan"]
        return {step.id: "pending" for step in plan.steps}, 0

    async def no_op(*args, **kwargs):
        return None

    async def next_sequence(*args, **kwargs):
        return 1

    async def ensure_approval(*args, **kwargs):
        call = kwargs["call"]
        spec = kwargs["spec"]
        approval_calls.append(call)
        return SimpleNamespace(
            id="approval-calendar",
            call_id=call["call_id"],
            tool_name=spec.name,
            side_effect_level=spec.side_effect.value,
            arguments=call["arguments"],
            status="pending",
        )

    async def emit(event_type, payload):
        events.append((event_type, payload))

    monkeypatch.setattr(loop, "_available_tool_specs", lambda payload: [calendar_spec])
    monkeypatch.setattr(loop, "_existing_deterministic_approval", no_op)
    monkeypatch.setattr(loop, "_restore_planning_decision", restore_decision)
    monkeypatch.setattr(loop, "_restore_or_persist_execution_plan", restore_plan)
    monkeypatch.setattr(loop, "_execution_plan_runtime", plan_runtime)
    monkeypatch.setattr(loop, "_persist_execution_plan_runtime", no_op)
    monkeypatch.setattr(loop, "_next_item_sequence", next_sequence)
    monkeypatch.setattr(loop, "_ensure_approval", ensure_approval)

    result = await loop.run(FakeDB(), response=response, emit=emit)

    assert result.status == "requires_action"
    assert result.intent is not None
    assert result.intent.capabilities == ("create_calendar_event",)
    assert approval_calls[0]["arguments"] == {
        "title": "开发会议",
        "start_at": "2026-08-01T14:00:00+08:00",
        "end_at": "2026-08-01T15:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "event_type": "meeting",
    }
    assert any(event_type == "response.requires_action" for event_type, _ in events)


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
