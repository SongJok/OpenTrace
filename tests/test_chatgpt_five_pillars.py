from pathlib import Path

from gateway.api_gateway.routers.responses import ResponseCreateRequest, extract_user_input
from infra.storage.models import Attachment, UserMemoryRelation
from kernel.agent_loop.context import ContextAssembler
from kernel.agent_loop.contracts import (
    ExecutionPlan,
    ExecutionProfile,
    ExecutionStep,
    IntentPlan,
    SideEffect,
    ToolSpec,
)
from kernel.agent_loop.discovery import CapabilityDiscovery
from kernel.agent_loop.runner import AgentLoop
from model.llm_adapter.openai_adapter import OpenAICompatibleAdapter

ROOT = Path(__file__).resolve().parents[1]


def _spec(name: str, description: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        parameters={"type": "object", "properties": {}},
        side_effect=SideEffect.READ,
    )


def test_agentic_plan_is_durable_provider_neutral_and_dependency_aware():
    plan = ExecutionPlan(
        goal="研究并验证结论",
        complexity="complex",
        steps=(
            ExecutionStep("s1", "检索证据", "web_search", success_criteria="有来源"),
            ExecutionStep("s2", "交叉验证", "rag", ("s1",), "结论一致"),
        ),
        success_criteria=("答案可核验",),
        replan_limit=3,
    )

    restored = ExecutionPlan.from_dict(plan.to_dict())
    restored_intent = IntentPlan.from_dict(
        IntentPlan(
            goal="研究并验证结论",
            capabilities=("web_search", "rag"),
            execution_profile=ExecutionProfile.DEEP,
        ).to_dict()
    )
    normalized = ExecutionPlan.from_dict(
        {
            "goal": "恢复异常计划",
            "complexity": "unknown",
            "replan_limit": 99,
            "steps": [
                {"id": "same", "objective": "第一步", "depends_on": ["future"]},
                {"id": "same", "objective": "第二步", "depends_on": ["same"]},
            ],
        }
    )

    assert restored == plan
    assert restored_intent.capabilities == ("web_search", "rag")
    assert restored_intent.execution_profile == ExecutionProfile.DEEP
    assert [step.id for step in normalized.steps] == ["same", "same_2"]
    assert normalized.steps[0].depends_on == ()
    assert normalized.steps[1].depends_on == ("same",)
    assert normalized.complexity == "simple"
    assert normalized.replan_limit == 3
    assert AgentLoop._plan_step_for_capability(restored, {"s1": "pending"}, "web_search")
    source = (ROOT / "kernel/agent_loop/runner.py").read_text(encoding="utf-8")
    assert 'item_type="agent_plan"' in source
    assert "_restore_planning_decision" in source
    assert 'payload["statuses"] = dict(statuses)' in source
    assert "opentrace.plan.replanned" in source
    assert "plan_dependency_not_ready" in source


def test_capability_discovery_uses_descriptions_and_preserves_client_tools():
    result = CapabilityDiscovery(catalogue_limit=8).discover(
        "查询最新天气并核对网络来源",
        [
            _spec("calculator", "计算数学表达式"),
            _spec("weather", "查询城市天气预报"),
            _spec("custom_connector", "调用租户自定义连接器"),
        ],
        pinned_names={"custom_connector"},
    )

    assert result.matches[0].name == "custom_connector"
    assert {item.name for item in result.matches} >= {"weather", "custom_connector"}
    prompt = AgentLoop._intent_planning_prompt(
        query="查天气",
        capability_names=[item.name for item in result.matches],
        attachment_context="",
        capability_catalogue=result.prompt_catalogue(),
    )
    assert "查询城市天气预报" in prompt


def test_long_context_packer_keeps_summary_current_turn_and_multimodal_budget():
    assembler = ContextAssembler(max_input_tokens=1_600)
    messages = [
        {"role": "system", "content": "平台安全边界"},
        {
            "role": "system",
            "content": "用户目标与已确认决定",
            "_context_kind": "conversation_summary",
        },
        *[
            {"role": "user" if index % 2 == 0 else "assistant", "content": "旧消息" * 300}
            for index in range(12)
        ],
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "当前问题"},
                {"type": "input_image", "image_url": "data:image/png;base64," + "A" * 500_000},
            ],
        },
    ]

    packed, manifest = assembler._pack_messages(
        messages,
        current_count=1,
        modality_counts={"text": 1, "image": 1, "audio": 0, "video": 0},
    )

    assert packed[-1]["role"] == "user"
    assert any(item.get("_context_kind") == "conversation_summary" for item in packed)
    assert manifest["dropped_history_items"] > 0
    assert manifest["used_conversation_summary"] is True
    assert assembler._content_tokens(messages[-1]["content"]) < 2_000


def test_native_multimodal_inputs_cover_image_audio_and_video():
    request = ResponseCreateRequest(
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": "data:audio/wav;base64,AA==", "format": "wav"},
                    }
                ],
            }
        ]
    )
    assert extract_user_input(request.input) == "请理解并处理用户提供的多模态内容。"
    normalized = OpenAICompatibleAdapter._chat_content(
        [
            {"type": "input_audio", "input_audio": {"data": "audio", "format": "mp3"}},
            {"type": "input_video", "video_url": {"url": "video"}},
        ]
    )
    assert normalized[0]["type"] == "input_audio"
    assert normalized[1] == {"type": "video_url", "video_url": {"url": "video"}}
    assert {"media_base64", "media_mime", "media_kind"} <= set(Attachment.__table__.columns.keys())


def test_memory_graph_is_postgresql_scoped_and_exposed_to_context_and_ui():
    assert UserMemoryRelation.__table__.name == "user_memory_relations"
    assert {"user_id", "tenant_id", "workspace_id"} <= set(
        UserMemoryRelation.__table__.columns.keys()
    )
    context_source = (ROOT / "kernel/agent_loop/context.py").read_text(encoding="utf-8")
    learner_source = (ROOT / "kernel/agent_loop/memory_learner.py").read_text(encoding="utf-8")
    frontend_source = (ROOT / "frontend/src/pages/MemoryPage.tsx").read_text(encoding="utf-8")
    assert "memory_graph_boosts" in context_source
    assert "link_memory_graph" in learner_source
    assert "记忆关系图" in frontend_source
    assert (ROOT / "alembic/versions/20260803_chatgpt_five_pillars.py").exists()


def test_rolling_summary_inherits_the_previous_durable_summary():
    source = (ROOT / "kernel/agent_loop/summarizer.py").read_text(encoding="utf-8")
    assert "上一版持久摘要" in source
    assert "[*previous_source_ids" in source
