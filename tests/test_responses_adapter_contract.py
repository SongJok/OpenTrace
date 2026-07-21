from types import SimpleNamespace

from model.llm_adapter.base import LLMConfig, LLMMessage
from model.llm_adapter.openai_adapter import OpenAICompatibleAdapter


def test_openai_adapter_selects_native_responses_transport():
    adapter = OpenAICompatibleAdapter(
        LLMConfig(
            provider="OpenAI",
            model="gpt-5.6",
            base_url="https://api.openai.com/v1",
            api_key="test-key",
        )
    )
    assert adapter._uses_responses_api is True


def test_compatible_provider_keeps_chat_completions_transport():
    adapter = OpenAICompatibleAdapter(
        LLMConfig(
            provider="阿里巴巴Qwen(DashScope)",
            model="qwen3.7-max",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="test-key",
        )
    )
    assert adapter._uses_responses_api is False


def test_response_output_is_normalized_to_tool_calls_and_items():
    function_call = SimpleNamespace(
        type="function_call",
        id="fc_1",
        call_id="call_1",
        name="search_docs",
        arguments='{"query":"roadmap"}',
    )
    message = SimpleNamespace(
        type="message",
        content=[SimpleNamespace(text="final answer")],
    )
    response = SimpleNamespace(output_text="final answer", output=[function_call, message])

    content, calls, items = OpenAICompatibleAdapter._parse_response_output(response)

    assert content == "final answer"
    assert calls == [
        {
            "id": "fc_1",
            "call_id": "call_1",
            "name": "search_docs",
            "arguments": '{"query":"roadmap"}',
            "type": "function_call",
        }
    ]
    assert items[0]["type"] == "function_call"
    assert items[-1]["type"] == "message"


def test_responses_input_preserves_tool_call_context():
    messages = [
        LLMMessage(role="assistant", content=None, tool_calls=[{"id": "fc_1"}]),
        LLMMessage(role="tool", content='{"ok":true}', tool_call_id="call_1", name="search_docs"),
    ]
    payload = OpenAICompatibleAdapter._response_input(messages)
    assert payload[0]["type"] == "function_call"
    assert payload[0]["call_id"] == "fc_1"
    assert payload[1]["type"] == "function_call_output"
    assert payload[1]["call_id"] == "call_1"
