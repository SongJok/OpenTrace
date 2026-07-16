from gateway.api_gateway.routers.responses import ResponseCreateRequest
from infra.config.settings import LLMSettings
from infra.storage.models import Project
from kernel.agent_loop.context import ContextAssembler
from model.llm_adapter.openai_adapter import OpenAICompatibleAdapter


def test_qwen_modes_have_provider_neutral_names_and_legacy_env_aliases(monkeypatch):
    monkeypatch.setenv("DEFAULT_LLM_FAST_OPENAI_MODEL", "legacy-fast-qwen")
    settings = LLMSettings()
    assert settings.default_llm_fast_model == "legacy-fast-qwen"
    assert settings.default_llm_fast_openai_model == "legacy-fast-qwen"
    assert settings.default_llm_deep_model == "qwen3.7-max"


def test_attachment_ids_are_normalized_into_opentrace_extension():
    request = ResponseCreateRequest(
        input="总结附件",
        conversation="conversation-1",
        attachment_ids=["attachment-1"],
    )
    assert request.opentrace.attachment_ids == ["attachment-1"]
    assert request.attachment_ids == ["attachment-1"]


def test_dashscope_multimodal_parts_and_thinking_are_normalized():
    content = OpenAICompatibleAdapter._chat_content(
        [
            {"type": "input_text", "text": "描述图片"},
            {"type": "input_image", "image_url": "data:image/png;base64,AA=="},
        ]
    )
    assert content == [
        {"type": "text", "text": "描述图片"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,AA=="},
        },
    ]
    assert OpenAICompatibleAdapter._qwen_thinking_enabled(
        {"reasoning": {"effort": "high"}}
    )
    assert not OpenAICompatibleAdapter._qwen_thinking_enabled(
        {"reasoning": {"effort": "low"}}
    )


def test_project_memory_isolation_and_chinese_relevance_terms_exist():
    assert "memory_mode" in Project.__table__.columns
    terms = ContextAssembler._search_terms("我偏好简洁的中文回答")
    assert "偏好" in terms
    assert "中文" in terms

