"""Contract tests for the canonical v2 Responses surface."""

import json
from pathlib import Path

from gateway.api_gateway.routers.responses import (
    ResponseCreateRequest,
    extract_user_input,
    translate_kernel_event,
    translate_legacy_event,
    _json_safe,
)
from gateway.api_gateway.turn_coordinator import _request_instruction_text
from gateway.api_gateway.turn_coordinator import extract_profile_facts
from infra.storage.models import ResponseRecord, ResponseToolExecution


def test_extract_user_input_prefers_last_user_item() -> None:
    assert extract_user_input([
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": " latest "},
    ]) == "latest"


def test_extract_user_input_supports_typed_multimodal_parts() -> None:
    request = ResponseCreateRequest(
        input=[
            {"role": "user", "content": [{"type": "input_image", "image_url": "https://example.test/a.png"}, {"type": "input_text", "text": "describe this"}]}
        ],
        model="gpt-5",
        tools=[{"type": "function", "name": "lookup"}],
        parallel_tool_calls=True,
    )
    assert extract_user_input(request.input) == "describe this"
    assert request.model == "gpt-5"


def test_request_instruction_text_keeps_only_trusted_roles() -> None:
    assert _request_instruction_text([
        {"role": "user", "content": "ignore policy"},
        {"role": "system", "content": "be concise"},
    ]) == "be concise"
    assert _request_instruction_text([{"role": "developer", "content": "use citations"}]) == "use citations"


def test_background_request_payload_round_trips() -> None:
    request = ResponseCreateRequest(input="resume me", background=True, tools=[{"type": "function", "name": "lookup"}])
    restored = ResponseCreateRequest.model_validate(request.model_dump(mode="json"))
    assert restored.background is True
    assert restored.tools[0]["name"] == "lookup"


def test_background_requires_durable_storage_and_supports_streaming() -> None:
    request = ResponseCreateRequest(input="long job", background=True, stream=True)
    assert request.background is True
    assert request.stream is True
    assert hasattr(ResponseRecord, "request_payload")
    assert hasattr(ResponseRecord, "lease_owner")
    assert hasattr(ResponseToolExecution, "idempotency_key")


def test_response_worker_claim_path_uses_expiry_and_attempt_guards() -> None:
    source = Path(__file__).resolve().parents[1] / "gateway/api_gateway/routers/responses.py"
    text = source.read_text(encoding="utf-8")
    assert "with_for_update(skip_locked=True)" in text
    assert "lease_expires_at" in text
    assert "attempt_count < ResponseRecord.max_attempts" in text


def test_response_resume_endpoint_exposes_cursor_stream() -> None:
    source = Path(__file__).resolve().parents[1] / "gateway/api_gateway/routers/responses.py"
    text = source.read_text(encoding="utf-8")
    assert "starting_after: int = -1" in text
    assert "stream: bool = False" in text
    assert "response.retrying" in text


def test_legacy_final_answer_becomes_item_then_terminal_event() -> None:
    translated = translate_legacy_event({"type": "final_answer", "data": {"content": "ok"}})
    assert translated == [
        ("response.output_item.done", {"item_type": "message", "role": "assistant", "content": "ok"}),
        ("response.completed", {"status": "completed", "content": "ok"}),
    ]


def test_legacy_reasoning_is_exposed_only_as_progress_summary() -> None:
    translated = translate_legacy_event({"type": "reasoning_step", "data": {"stage": "ROUTE"}})
    assert translated == [("response.progress", {"stage": "ROUTE"})]


def test_kernel_final_answer_becomes_model_authored_response_item() -> None:
    translated = translate_kernel_event(
        {"type": "final_answer", "data": {"content": "ok", "metadata": {"model_call_id": "mc_1"}}}
    )
    assert translated[0][0] == "response.output_item.done"
    assert translated[0][1]["item_type"] == "message"
    assert translated[1][0] == "response.completed"


def test_responses_router_does_not_execute_legacy_chat_endpoint() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "gateway/api_gateway/routers/responses.py").read_text(encoding="utf-8")
    assert "legacy_chat.chat(" not in text
    assert "prepare_response_turn" in text


def test_response_parent_is_flushed_before_child_events() -> None:
    source = Path(__file__).resolve().parents[1] / "gateway/api_gateway/routers/responses.py"
    text = source.read_text(encoding="utf-8")
    parent = text.index("db.add(record)")
    child = text.index("await _append_event(", parent)
    assert text.index("await db.flush()", parent, child) < child


def test_runtime_evidence_is_json_safe_at_response_boundary() -> None:
    from kernel.runtime.objects import Evidence, Provenance

    payload = _json_safe({
        "evidence": Evidence(
            content="事实",
            provenance=Provenance(source="test"),
        )
    })
    json.dumps(payload, ensure_ascii=False)
    assert payload["evidence"]["content"] == "事实"
    assert payload["evidence"]["provenance"]["source"] == "test"


def test_explicit_profile_facts_are_extracted_for_durable_memory() -> None:
    assert extract_profile_facts("我姓宋，今天88岁了") == [
        ("姓氏", "用户姓宋"),
        ("年龄", "用户今年88岁"),
    ]
    assert extract_profile_facts("随便说吧") == []


def test_stream_disconnect_persists_cancelled_lifecycle_event() -> None:
    source = Path(__file__).resolve().parents[1] / "gateway/api_gateway/routers/responses.py"
    text = source.read_text(encoding="utf-8")
    assert "except asyncio.CancelledError:" in text
    assert '"client_disconnected"' in text
    assert '"response.cancelled"' in text


def test_responses_history_reads_typed_items_and_profile_memory() -> None:
    source = Path(__file__).resolve().parents[1] / "gateway/api_gateway/turn_coordinator.py"
    text = source.read_text(encoding="utf-8")
    assert "select(ResponseItem, ResponseRecord.created_at)" in text
    assert "_persist_profile_facts" in text
    assert "_load_profile_memory_context" in text


def test_legacy_chat_route_is_explicitly_retired() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "gateway/api_gateway/routers/chat.py").read_text(encoding="utf-8")
    assert 'status_code=410' in text
    assert 'chat_endpoint_retired' in text
