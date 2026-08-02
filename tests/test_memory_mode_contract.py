"""Temporary conversations must never consume personalization memory."""

import asyncio
from types import SimpleNamespace

from gateway.api_gateway.routers.responses import ResponseCreateRequest
from kernel.turn_enrichment import apply_preference_and_memory, personalization_memory_enabled


def test_memory_mode_defaults_to_enabled_for_responses_clients() -> None:
    assert ResponseCreateRequest(input="hello").memory_mode == "enabled"


def test_temporary_memory_mode_skips_personalization_reads() -> None:
    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        query="hello",
        conversation_state=None,
        metadata={
            "memory_mode": "temporary",
            "user_preferences": ["must not be used"],
            "user_preference_context_block": "must not be used",
        },
    )

    result = asyncio.run(apply_preference_and_memory(request))

    assert not personalization_memory_enabled(request.metadata)
    assert result.memory_context == []
    assert result.metadata["memory_status"] == "disabled"
    assert "user_preferences" not in result.metadata
    assert "user_preference_context_block" not in result.metadata


def test_conversational_memory_capture_cannot_expand_into_file_write() -> None:
    from kernel.agent_loop.runner import AgentLoop

    parsed = {
        "goal": "记录用户偏好",
        "task_type": "memory_write",
        "capabilities": ["file_sandbox"],
        "steps": [
            {
                "id": "1",
                "objective": "写入文件",
                "capability": "file_sandbox",
                "depends_on": [],
                "success_criteria": "文件存在",
            }
        ],
        "success_criteria": ["已保存"],
    }

    result = AgentLoop._apply_conversational_memory_policy("请记住：我偏好简洁回答", parsed)

    assert result["task_type"] == "memory_capture"
    assert result["capabilities"] == []
    assert result["steps"][0]["capability"] is None
    assert "file_sandbox" not in str(result["steps"])

    fallback = AgentLoop._apply_conversational_memory_policy("请记住：我的代号是北辰", {})
    assert fallback["task_type"] == "memory_capture"
    assert fallback["capabilities"] == []
    assert fallback["replan_limit"] == 0


def test_explicit_file_write_is_not_misclassified_as_memory_learning() -> None:
    from kernel.agent_loop.runner import AgentLoop

    assert AgentLoop._is_conversational_memory_capture("请记住：我偏好简洁回答") is True
    assert AgentLoop._is_conversational_memory_capture("请把这段内容写入文件 notes.md") is False
    assert AgentLoop._is_conversational_memory_capture("请记住并保存到文件 notes.md") is False
    assert AgentLoop._is_conversational_memory_capture("请忘记我的代号") is True
    assert AgentLoop._is_conversational_memory_capture("请删除我的记忆文件 notes.md") is False


def test_context_declares_memory_learning_boundary_to_manager() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "kernel/agent_loop/context.py").read_text(
        encoding="utf-8"
    )
    assert "持久记忆由 Response 完成后的受治理 MemoryLearner 统一处理" in source
    assert "当前会话未启用持久记忆学习" in source
    assert '"memory_learning_enabled": memory_learning_enabled' in source


def test_execution_plan_preserves_zero_replan_limit() -> None:
    from kernel.agent_loop.contracts import ExecutionPlan

    plan = ExecutionPlan.from_dict(
        {
            "goal": "直接回应",
            "steps": [
                {
                    "id": "step-1",
                    "objective": "回答",
                    "capability": None,
                    "depends_on": [],
                    "success_criteria": "完成",
                }
            ],
            "replan_limit": 0,
        }
    )

    assert plan.replan_limit == 0


def test_memory_e2e_polls_durable_response_until_terminal_status() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "scripts/verify_memory_e2e.sh").read_text(
        encoding="utf-8"
    )
    assert "def wait_for_response" in source
    assert 'request(f"/api/v2/responses/{response_id}")' in source
    assert "result = wait_for_response(result)" in source
    assert '"queued"' not in source.split("def wait_for_response", 1)[1].split("def respond", 1)[0]


def test_memory_e2e_waits_for_async_candidate_projection() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "scripts/verify_memory_e2e.sh").read_text(
        encoding="utf-8"
    )
    assert "def wait_for_candidate" in source
    assert "wait_for_candidate(reinforcement_marker, observations=1)" in source
    assert source.count('f"我的常用技术栈是 {reinforcement_marker}。"') == 2


def test_direct_memory_question_uses_confirmed_memory_projection() -> None:
    from kernel.agent_loop.runner import AgentLoop

    answer = AgentLoop._direct_memory_answer(
        "我的代号是什么？",
        [
            {"id": "memory-new", "content": "我的代号是北辰-42"},
            {"id": "memory-other", "content": "我偏好简洁中文回答"},
        ],
    )

    assert answer == "根据你已确认的记忆，我的代号是北辰-42。"


def test_direct_memory_projection_never_handles_memory_mutation() -> None:
    from kernel.agent_loop.runner import AgentLoop

    memories = [{"id": "memory-1", "content": "我的代号是北辰-42"}]

    assert AgentLoop._direct_memory_answer("请修改我的代号为星河", memories) is None
    assert AgentLoop._direct_memory_answer("请忘记我的代号", memories) is None
    assert AgentLoop._direct_memory_answer("我的代号是什么？然后查天气", memories) is None
    assert AgentLoop._direct_memory_answer("介绍一下企业知识库", memories) is None
    assert (
        AgentLoop._direct_memory_answer(
            "我的工资是多少？",
            [{"id": "memory-preference", "content": "我的偏好是简洁中文回答"}],
        )
        is None
    )


def test_direct_memory_projection_accepts_value_only_presentation_suffix() -> None:
    from kernel.agent_loop.runner import AgentLoop

    answer = AgentLoop._direct_memory_answer(
        "我的代号是什么？只回答当前有效值。",
        [{"id": "memory-current", "content": "我的代号是 星轨-9152"}],
    )

    assert answer == "星轨-9152"


def test_disabled_memory_learning_cannot_claim_persistence() -> None:
    from kernel.agent_loop.contracts import ExecutionProfile, IntentPlan, SideEffect
    from kernel.agent_loop.runner import AgentLoop

    intent = IntentPlan(
        goal="记住代号",
        task_type="memory_capture",
        capabilities=(),
        risk=SideEffect.READ,
        execution_profile=ExecutionProfile.AUTO,
    )
    governed = AgentLoop._govern_memory_capture_response(
        intent=intent,
        context_manifest={"memory_learning_enabled": False},
        model_content="好的，我已经永久记住了。",
    )
    assert governed == "当前持久记忆学习已关闭，本次不会新增、更新或遗忘个人记忆。"
