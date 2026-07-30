"""Contract tests for the canonical v2 Responses surface."""

import json
from pathlib import Path

from gateway.api_gateway.routers.responses import (
    ResponseCreateRequest,
    _json_safe,
    extract_user_input,
)
from infra.storage.models import ResponseRecord, ResponseToolExecution
from kernel.agent_loop.contracts import parse_tool_specs


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
    source = Path(__file__).resolve().parents[1] / "infra/responses/repository.py"
    text = source.read_text(encoding="utf-8")
    assert "with_for_update(skip_locked=True)" in text
    assert "lease_expires_at" in text
    assert "attempt_count < ResponseRecord.max_attempts" in text


def test_response_resume_endpoint_exposes_cursor_stream() -> None:
    source = Path(__file__).resolve().parents[1] / "gateway/api_gateway/routers/responses.py"
    text = source.read_text(encoding="utf-8")
    assert "starting_after: int = -1" in text
    assert "stream: bool = False" in text
    worker = (Path(__file__).resolve().parents[1] / "infra/responses/worker.py").read_text(encoding="utf-8")
    assert 'event_type="response.in_progress"' in worker


def test_responses_router_has_no_legacy_event_translation() -> None:
    source = Path(__file__).resolve().parents[1] / "gateway/api_gateway/routers/responses.py"
    text = source.read_text(encoding="utf-8")
    assert "translate_legacy_event" not in text
    assert "translate_kernel_event" not in text


def test_responses_router_does_not_execute_legacy_chat_endpoint() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "gateway/api_gateway/routers/responses.py").read_text(encoding="utf-8")
    assert "legacy_chat.chat(" not in text
    assert "AgentLoop" not in text
    assert "add_outbox" in text


def test_conversation_reuse_keeps_org_boundary() -> None:
    source = Path(__file__).resolve().parents[1] / "gateway/api_gateway/routers/responses.py"
    text = source.read_text(encoding="utf-8")
    assert "ChatSession.org_id == org_id" in text


def test_api_process_does_not_start_execution_background_loops() -> None:
    root = Path(__file__).resolve().parents[1]
    api_main = (root / "gateway/api_gateway/main.py").read_text(encoding="utf-8")
    worker = (root / "agents/worker.py").read_text(encoding="utf-8")
    assert "asyncio.create_task" not in api_main
    assert "response_job_loop()" in worker
    assert "scheduler_loop()" in worker
    assert "memory_event_subscriber.start()" in worker


def test_response_parent_is_flushed_before_child_events() -> None:
    source = Path(__file__).resolve().parents[1] / "gateway/api_gateway/routers/responses.py"
    text = source.read_text(encoding="utf-8")
    parent = text.index("db.add(record)")
    child = text.index("await append_event(", parent)
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


def test_stream_disconnect_does_not_cancel_durable_response() -> None:
    source = Path(__file__).resolve().parents[1] / "gateway/api_gateway/routers/responses.py"
    text = source.read_text(encoding="utf-8")
    assert "client_disconnected" not in text
    assert "_event_stream" in text
    assert "starting_after" in text


def test_responses_history_reads_only_typed_items_and_scoped_memory() -> None:
    source = Path(__file__).resolve().parents[1] / "kernel/agent_loop/context.py"
    text = source.read_text(encoding="utf-8")
    assert "select(ResponseItem)" in text
    assert "UserMemory.scope_type" in text
    assert "TraceLog" not in text
    assert "Message" not in text


def test_legacy_chat_route_is_explicitly_retired() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "gateway/api_gateway/routers/chat.py").read_text(encoding="utf-8")
    assert 'status_code=410' in text
    assert 'chat_endpoint_retired' in text


def test_temporary_conversations_expire_and_reject_durable_resource_binding() -> None:
    source = Path(__file__).resolve().parents[1] / "gateway/api_gateway/routers/responses.py"
    text = source.read_text(encoding="utf-8")
    assert "timedelta(days=30)" in text
    assert "临时对话不能加入 Project 或 Goal" in text


def test_side_effect_tools_disable_both_retry_layers() -> None:
    source = Path(__file__).resolve().parents[1] / "kernel/agent_loop/runner.py"
    text = source.read_text(encoding="utf-8")
    assert "max_retries=spec.max_retries if spec.side_effect == SideEffect.READ else 0" in text
    assert "side_effect_outcome_unknown" in text


def test_tool_spec_preserves_explicit_zero_retry_policy() -> None:
    spec = parse_tool_specs([
        {
            "type": "function",
            "name": "external_write",
            "parameters": {"type": "object", "properties": {}},
            "opentrace": {"side_effect": "write", "max_retries": 0},
        }
    ])[0]
    assert spec.max_retries == 0
