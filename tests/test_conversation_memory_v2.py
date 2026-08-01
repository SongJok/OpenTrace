from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from infra.storage.models import UserMemory
from kernel.agent_loop.context import ContextAssembler
from kernel.agent_loop.memory_learner import MemoryLearner
from kernel.agent_loop.summarizer import ConversationSummarizer
from kernel.agent_loop.write_intent import is_contextual_follow_up


def test_structured_checkpoint_is_normalized_and_rendered() -> None:
    state = ConversationSummarizer._parse_structured_state(
        """```json
        {
          "current_goal": "完成企业记忆优化",
          "constraints": ["提交 main", "保持租户隔离"],
          "decisions": ["使用 Responses 主链路"],
          "open_items": ["运行完整测试"],
          "confirmed_facts": [],
          "tool_evidence": ["测试尚未执行"],
          "recent_turns": ["用户要求继续开发"]
        }
        ```"""
    )

    assert state is not None
    assert state["current_goal"] == "完成企业记忆优化"
    rendered = ConversationSummarizer._render_structured_state(state)
    assert "对话连续性检查点" in rendered
    assert "## 未完成事项" in rendered
    assert "运行完整测试" in rendered


def test_invalid_checkpoint_keeps_compatibility_fallback() -> None:
    assert ConversationSummarizer._parse_structured_state("普通自由文本摘要") is None
    assert ConversationSummarizer._parse_structured_state("{}") is None


def test_checkpoint_transcript_contains_tool_arguments_and_outcome() -> None:
    call = SimpleNamespace(
        response_id="resp-1",
        item_type="function_call",
        role="assistant",
        content="",
        payload={
            "name": "create_calendar_event",
            "call_id": "call-1",
            "arguments": {"title": "项目复盘"},
            "status": "requires_action",
        },
    )
    output = SimpleNamespace(
        response_id="resp-2",
        item_type="function_call_output",
        role="tool",
        content="日程已创建",
        payload={"name": "create_calendar_event", "call_id": "call-1", "status": "succeeded"},
    )

    call_line = ConversationSummarizer._transcript_line(call)
    output_line = ConversationSummarizer._transcript_line(output)

    assert "requires_action" in call_line
    assert "项目复盘" in call_line
    assert "succeeded" in output_line
    assert "日程已创建" in output_line


def test_response_parent_chain_requires_full_enterprise_scope() -> None:
    response = SimpleNamespace(
        conversation_id="conversation-1",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
    )
    same = SimpleNamespace(**vars(response))
    other_workspace = SimpleNamespace(**{**vars(response), "workspace_id": "workspace-2"})
    other_user = SimpleNamespace(**{**vars(response), "user_id": "user-2"})

    assert ContextAssembler._same_response_scope(same, response) is True
    assert ConversationSummarizer._same_scope(same, response) is True
    assert ContextAssembler._same_response_scope(other_workspace, response) is False
    assert ConversationSummarizer._same_scope(other_user, response) is False


def test_memory_correction_uses_stable_key_and_authoritative_mode() -> None:
    old = MemoryLearner.deterministic_candidates("我的技术栈是 Python 和 React")
    corrected = MemoryLearner.deterministic_candidates("更正一下，我的技术栈是 Rust 和 React。")
    current = MemoryLearner.deterministic_candidates("我的技术栈现在是 Go 和 React。")
    negative = MemoryLearner.deterministic_candidates(
        "我的技术栈不是 Java 和 Vue，而是 TypeScript 和 React。"
    )

    assert old[0]["key"] == corrected[0]["key"] == current[0]["key"] == negative[0]["key"]
    assert corrected[0]["_learning_mode"] == "correction"
    assert corrected[0]["explicit"] is False
    assert corrected[0]["content"] == "我的技术栈是 Rust 和 React"
    assert current[0]["content"] == "我的技术栈是 Go 和 React"
    assert negative[0]["content"] == "我的技术栈是 TypeScript 和 React"


def test_explicit_memory_and_correction_share_the_same_stable_key() -> None:
    original = MemoryLearner.deterministic_candidates("请记住：我的代号是苍穹-8041。")
    corrected = MemoryLearner.deterministic_candidates("更正一下，我的代号是星轨-9152。")

    assert original[0]["key"] == corrected[0]["key"]
    assert original[0]["key"].startswith("fact.")
    assert corrected[0]["_learning_mode"] == "correction"


def test_transient_statement_is_never_promoted_as_correction() -> None:
    candidates = MemoryLearner.deterministic_candidates("今天我的技术栈改为 Rust")

    assert candidates == []


def test_name_correction_reuses_existing_profile_key() -> None:
    original = MemoryLearner.deterministic_candidates("我叫小林")
    corrected = MemoryLearner.deterministic_candidates("更正一下，我的名字是林舟。")

    assert original[0]["key"] == corrected[0]["key"] == "profile.name"
    assert corrected[0]["content"] == "我的名字是 林舟"


def test_contextual_follow_up_expands_memory_retrieval_from_current_branch() -> None:
    history = [
        {"role": "user", "content": "公司的印章借用流程是什么？"},
        {"role": "assistant", "content": "请在钉钉 OA 审批中提交印章借用申请。"},
    ]

    expanded, used_history = ContextAssembler._expanded_retrieval_query(
        "那具体怎么操作？",
        history,
    )

    assert is_contextual_follow_up("那具体怎么操作？") is True
    assert used_history is True
    assert "印章借用流程" in expanded
    assert "钉钉 OA 审批" in expanded


def test_standalone_memory_query_is_not_polluted_by_old_branch_content() -> None:
    expanded, used_history = ContextAssembler._expanded_retrieval_query(
        "财务报销制度是什么？",
        [{"role": "user", "content": "上一个无关问题"}],
    )

    assert expanded == "财务报销制度是什么？"
    assert used_history is False


def test_memory_database_search_terms_keep_subject_and_drop_follow_up_noise() -> None:
    terms = ContextAssembler._memory_search_terms(
        "那具体怎么操作？\n最近对话主题：\n我的内部项目代号是星轨-9152"
    )

    assert "代号" in terms
    assert "星轨" in terms
    assert "最近" not in terms
    assert "主题" not in terms
    assert len(terms) <= 24


@pytest.mark.asyncio
async def test_memory_candidate_pool_merges_priority_and_lexical_hits() -> None:
    priority = SimpleNamespace(id="memory-priority")
    lexical = SimpleNamespace(id="memory-old-but-relevant")

    class Rows:
        def __init__(self, rows):
            self.rows = rows

        def scalars(self):
            return self

        def all(self):
            return list(self.rows)

    class Session:
        def __init__(self):
            self.calls = 0
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            self.calls += 1
            return Rows([priority]) if self.calls == 1 else Rows([lexical, priority])

    db = Session()
    memories, lexical_count = await ContextAssembler._memory_candidate_pool(
        db,
        response=SimpleNamespace(
            user_id="user-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
        ),
        scope_clause=UserMemory.scope_type == "user",
        now=datetime.now(UTC),
        query="我的内部项目代号是什么？",
    )

    assert [memory.id for memory in memories] == ["memory-priority", "memory-old-but-relevant"]
    assert lexical_count == 2
    assert len(db.statements) == 2
    for statement in db.statements:
        sql = str(statement)
        assert "user_memories.user_id" in sql
        assert "user_memories.tenant_id" in sql
        assert "user_memories.workspace_id" in sql


@pytest.mark.asyncio
async def test_personal_business_context_is_scoped_and_redacts_raw_tool_payload() -> None:
    task = SimpleNamespace(
        id="task-1",
        title="每日销售简报",
        status="active",
        next_run_at=datetime(2026, 8, 2, 1, 0, tzinfo=UTC),
    )
    approval = SimpleNamespace(
        id="approval-1",
        tool_name="create_calendar_event",
        created_at=datetime(2026, 8, 1, 1, 0, tzinfo=UTC),
    )
    approval_response = SimpleNamespace(id="resp-approval")
    execution = SimpleNamespace(
        tool_name="create_calendar_event",
        completed_at=datetime(2026, 8, 1, 2, 0, tzinfo=UTC),
        arguments={"title": "客户复盘", "password": "must-not-leak"},
        result={"event_id": "event-1", "access_token": "must-not-leak"},
    )
    execution_response = SimpleNamespace(id="resp-operation")

    class Rows:
        def __init__(self, rows):
            self.rows = rows

        def scalars(self):
            return self

        def all(self):
            return list(self.rows)

    class Session:
        def __init__(self):
            self.calls = 0
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            self.calls += 1
            return (
                Rows([task])
                if self.calls == 1
                else (
                    Rows([(approval, approval_response)])
                    if self.calls == 2
                    else Rows([(execution, execution_response)])
                )
            )

    db = Session()
    prompt, manifest = await ContextAssembler._personal_business_context(
        db,
        response=SimpleNamespace(
            user_id="user-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
        ),
        query="我刚才创建的任务和待审批操作是什么状态？",
        timezone_name="Asia/Shanghai",
    )

    assert "每日销售简报" in prompt
    assert "approval-1" in prompt
    assert "客户复盘" in prompt
    assert "event-1" in prompt
    assert "must-not-leak" not in prompt
    assert manifest == {
        "query_matched": True,
        "scheduled_task_count": 1,
        "pending_approval_count": 1,
        "recent_operation_count": 1,
    }
    assert len(db.statements) == 3
    for statement in db.statements:
        sql = str(statement)
        assert "responses.user_id" in sql or "task_definitions.user_id" in sql
        assert "responses.tenant_id" in sql or "task_definitions.tenant_id" in sql
        assert "responses.workspace_id" in sql or "task_definitions.workspace_id" in sql


def test_summary_is_due_for_many_short_responses() -> None:
    summarizer = ConversationSummarizer(
        minimum_chars=40_000,
        minimum_tokens=48_000,
        minimum_new_responses=8,
    )

    assert summarizer._summary_due(total_chars=800, total_tokens=300, response_count=8) is True
    assert summarizer._summary_due(total_chars=800, total_tokens=300, response_count=7) is False


def test_deterministic_checkpoint_preserves_business_continuity() -> None:
    items = [
        SimpleNamespace(
            response_id="resp-8",
            item_type="input_message",
            role="user",
            content="继续完善客户复盘任务",
            payload={},
        ),
        SimpleNamespace(
            response_id="resp-8",
            item_type="function_call_output",
            role="tool",
            content="任务已创建",
            payload={
                "name": "create_scheduled_task",
                "call_id": "call-8",
                "status": "succeeded",
            },
        ),
    ]

    state = ConversationSummarizer._deterministic_state(
        items,
        previous_state={
            "current_goal": "旧目标",
            "constraints": ["仅使用当前工作区数据"],
            "decisions": [],
            "open_items": [],
            "confirmed_facts": [],
            "tool_evidence": [],
            "recent_turns": [],
        },
    )

    assert state["current_goal"] == "继续完善客户复盘任务"
    assert state["constraints"] == ["仅使用当前工作区数据"]
    assert "create_scheduled_task" in state["tool_evidence"][0]
    assert "任务已创建" in state["tool_evidence"][0]
