from types import SimpleNamespace

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
