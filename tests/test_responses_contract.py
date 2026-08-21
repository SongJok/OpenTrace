"""Contract tests for the canonical v2 Responses surface."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.api_gateway.routers.response_aux import (
    _ensure_approval_resume_outbox,
    _owned_response,
    _prepare_response_for_approval_resume,
    _resolve_response_tool_approval,
)
from gateway.api_gateway.routers.responses import (
    ResponseCreateRequest,
    _json_safe,
    extract_user_input,
)
from infra.errors import AppException
from infra.responses.worker import _valid_terminal_content
from infra.storage.models import ResponseRecord, ResponseToolExecution
from kernel.agent_loop.contracts import parse_tool_specs


def test_worker_rejects_null_like_terminal_content() -> None:
    assert _valid_terminal_content(None) is None
    assert _valid_terminal_content(" null ") is None
    assert _valid_terminal_content("undefined") is None
    assert _valid_terminal_content("正常回答") == "正常回答"


def test_extract_user_input_prefers_last_user_item() -> None:
    assert (
        extract_user_input(
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "answer"},
                {"role": "user", "content": " latest "},
            ]
        )
        == "latest"
    )


def test_extract_user_input_supports_typed_multimodal_parts() -> None:
    request = ResponseCreateRequest(
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_image", "image_url": "https://example.test/a.png"},
                    {"type": "input_text", "text": "describe this"},
                ],
            }
        ],
        model="gpt-5",
        tools=[{"type": "function", "name": "lookup"}],
        parallel_tool_calls=True,
    )
    assert extract_user_input(request.input) == "describe this"
    assert request.model == "gpt-5"


def test_background_request_payload_round_trips() -> None:
    request = ResponseCreateRequest(
        input="resume me", background=True, tools=[{"type": "function", "name": "lookup"}]
    )
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


def test_response_model_selection_is_snapshotted_for_worker_recovery() -> None:
    root = Path(__file__).resolve().parents[1]
    router = (root / "gateway/api_gateway/routers/responses.py").read_text(encoding="utf-8")
    worker = (root / "infra/responses/worker.py").read_text(encoding="utf-8")
    conversations = (root / "gateway/api_gateway/routers/conversations.py").read_text(
        encoding="utf-8"
    )
    scheduler = (root / "infra/responses/scheduler.py").read_text(encoding="utf-8")

    assert "model_selection = await snapshot_runtime_llm_selection(" in router
    assert '"model_selection": model_selection' in router
    assert 'selection=(response.response_metadata or {}).get("model_selection")' in worker
    edit_branch = conversations.split("async def edit_message_and_branch(", 1)[1].split(
        "async def branch_conversation(", 1
    )[0]
    assert "model_selection = await snapshot_runtime_llm_selection(" in edit_branch
    assert '"model_selection": model_selection' in edit_branch
    assert "model_selection = await snapshot_runtime_llm_selection(" in scheduler


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
    worker = (Path(__file__).resolve().parents[1] / "infra/responses/worker.py").read_text(
        encoding="utf-8"
    )
    assert 'event_type="response.in_progress"' in worker


def test_approval_resolution_preserves_one_worker_resume_attempt() -> None:
    response = SimpleNamespace(
        status="requires_action",
        completed_at=datetime.now(UTC),
        lease_owner="worker-old",
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
        heartbeat_at=datetime.now(UTC),
        attempt_count=3,
        max_attempts=3,
    )

    _prepare_response_for_approval_resume(response)

    assert response.status == "queued"
    assert response.completed_at is None
    assert response.lease_owner is None
    assert response.lease_expires_at is None
    assert response.heartbeat_at is None
    assert response.max_attempts == 4


def _approval_request():
    return SimpleNamespace(headers={})


def _approval_response(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="resp-1",
        status=status,
        completed_at=None,
        lease_owner=None,
        lease_expires_at=None,
        heartbeat_at=None,
        attempt_count=1,
        max_attempts=3,
    )


def _approval(
    status: str,
    *,
    required_approvals: int = 1,
    approval_decisions: list[dict] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="approval-1",
        call_id="call-1",
        status=status,
        required_approvals=required_approvals,
        approval_decisions=list(approval_decisions or []),
        reason=None,
        resolved_by=None,
        resolved_at=None,
    )


@pytest.mark.asyncio
async def test_owned_response_can_be_loaded_under_row_lock(monkeypatch) -> None:
    db = AsyncMock()
    expected = _approval_response("requires_action")
    db.scalar.return_value = expected
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._scope",
        lambda *_args, **_kwargs: ("default", "default"),
    )

    result = await _owned_response(
        db,
        response_id=expected.id,
        user=SimpleNamespace(id="user-1"),
        request=_approval_request(),
        for_update=True,
    )

    assert result is expected
    statement = db.scalar.await_args.args[0]
    assert statement._for_update_arg is not None
    assert statement.get_execution_options()["populate_existing"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("response_status", ["completed", "failed", "cancelled", "incomplete"])
@pytest.mark.parametrize("approval_status", ["pending", "approved", "rejected"])
async def test_terminal_response_rejects_stale_approval_without_requeue(
    monkeypatch,
    response_status: str,
    approval_status: str,
) -> None:
    response = _approval_response(response_status)
    approval = _approval(approval_status)
    db = AsyncMock()
    db.scalar.return_value = approval
    owned_response = AsyncMock(return_value=response)
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._owned_response",
        owned_response,
    )
    ensure_outbox = AsyncMock()
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._ensure_approval_resume_outbox",
        ensure_outbox,
    )

    with pytest.raises(AppException) as exc_info:
        await _resolve_response_tool_approval(
            response_id=response.id,
            request=_approval_request(),
            payload={"approved": True},
            current_user=SimpleNamespace(id="user-1"),
            db=db,
            approval_id=approval.id,
        )

    assert exc_info.value.http_status == 409
    assert response.status == response_status
    assert approval.status == approval_status
    assert db.scalar.await_args.args[0]._for_update_arg is not None
    assert owned_response.await_args.kwargs["for_update"] is True
    ensure_outbox.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("response_status", ["queued", "in_progress"])
async def test_pending_approval_only_transitions_from_requires_action(
    monkeypatch,
    response_status: str,
) -> None:
    response = _approval_response(response_status)
    approval = _approval("pending")
    db = AsyncMock()
    db.scalar.return_value = approval
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._owned_response",
        AsyncMock(return_value=response),
    )
    ensure_outbox = AsyncMock()
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._ensure_approval_resume_outbox",
        ensure_outbox,
    )

    with pytest.raises(AppException) as exc_info:
        await _resolve_response_tool_approval(
            response_id=response.id,
            request=_approval_request(),
            payload={"approved": True},
            current_user=SimpleNamespace(id="user-1"),
            db=db,
            approval_id=approval.id,
        )

    assert exc_info.value.http_status == 409
    assert response.status == response_status
    assert approval.status == "pending"
    ensure_outbox.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_approval_transitions_and_requeues_from_requires_action(monkeypatch) -> None:
    response = _approval_response("requires_action")
    approval = _approval("pending")
    db = AsyncMock()
    db.scalar.side_effect = [approval, None]
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._owned_response",
        AsyncMock(return_value=response),
    )
    append_event = AsyncMock(return_value=SimpleNamespace(sequence_number=12))
    ensure_outbox = AsyncMock()
    monkeypatch.setattr("gateway.api_gateway.routers.response_aux.append_event", append_event)
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._ensure_approval_resume_outbox",
        ensure_outbox,
    )

    result = await _resolve_response_tool_approval(
        response_id=response.id,
        request=_approval_request(),
        payload={"approved": True},
        current_user=SimpleNamespace(id="user-1"),
        db=db,
        approval_id=approval.id,
    )

    assert result["status"] == "approved"
    assert result["starting_after"] == 12
    assert response.status == "queued"
    assert approval.status == "approved"
    assert db.scalar.await_args_list[0].args[0]._for_update_arg is not None
    append_event.assert_awaited_once()
    ensure_outbox.assert_awaited_once_with(
        db,
        response_id=response.id,
        approval_id="approval-1",
    )
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_destructive_production_approval_requires_two_distinct_approvers(monkeypatch) -> None:
    response = _approval_response("requires_action")
    approval = _approval("pending", required_approvals=2)
    first_db = AsyncMock()
    first_db.scalar.return_value = approval
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._owned_response",
        AsyncMock(return_value=response),
    )
    append_event = AsyncMock(
        side_effect=[SimpleNamespace(sequence_number=12), SimpleNamespace(sequence_number=13)]
    )
    ensure_outbox = AsyncMock()
    monkeypatch.setattr("gateway.api_gateway.routers.response_aux.append_event", append_event)
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._ensure_approval_resume_outbox",
        ensure_outbox,
    )

    first = await _resolve_response_tool_approval(
        response_id=response.id,
        request=_approval_request(),
        payload={"approved": True},
        current_user=SimpleNamespace(id="sre-1"),
        db=first_db,
        approval_id=approval.id,
    )

    assert first["status"] == "pending_secondary"
    assert first["received_approvals"] == 1
    assert response.status == "requires_action"
    assert approval.status == "pending_secondary"
    assert approval.approval_decisions[0]["user_id"] == "sre-1"
    ensure_outbox.assert_not_awaited()

    tool = SimpleNamespace(status="pending_approval", error_message=None)
    second_db = AsyncMock()
    second_db.scalar.side_effect = [approval, tool]
    second = await _resolve_response_tool_approval(
        response_id=response.id,
        request=_approval_request(),
        payload={"approved": True},
        current_user=SimpleNamespace(id="sre-2"),
        db=second_db,
        approval_id=approval.id,
    )

    assert second["status"] == "approved"
    assert second["received_approvals"] == 2
    assert response.status == "queued"
    assert approval.status == "approved"
    assert tool.status == "approved"
    assert {item["user_id"] for item in approval.approval_decisions} == {"sre-1", "sre-2"}
    ensure_outbox.assert_awaited_once_with(
        second_db,
        response_id=response.id,
        approval_id=approval.id,
    )


@pytest.mark.asyncio
async def test_same_approver_cannot_count_twice_for_four_eye_approval(monkeypatch) -> None:
    response = _approval_response("requires_action")
    approval = _approval(
        "pending_secondary",
        required_approvals=2,
        approval_decisions=[
            {
                "user_id": "sre-1",
                "approved": True,
                "reason": None,
                "decided_at": datetime.now(UTC).isoformat(),
            }
        ],
    )
    db = AsyncMock()
    db.scalar.side_effect = [approval, 12]
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._owned_response",
        AsyncMock(return_value=response),
    )
    ensure_outbox = AsyncMock()
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._ensure_approval_resume_outbox",
        ensure_outbox,
    )

    result = await _resolve_response_tool_approval(
        response_id=response.id,
        request=_approval_request(),
        payload={"approved": True},
        current_user=SimpleNamespace(id="sre-1"),
        db=db,
        approval_id=approval.id,
    )

    assert result["status"] == "pending_secondary"
    assert result["received_approvals"] == 1
    assert approval.status == "pending_secondary"
    assert len(approval.approval_decisions) == 1
    ensure_outbox.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeated_approval_cannot_reverse_existing_decision(monkeypatch) -> None:
    response = _approval_response("requires_action")
    approval = _approval("approved")
    db = AsyncMock()
    db.scalar.return_value = approval
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._owned_response",
        AsyncMock(return_value=response),
    )

    with pytest.raises(AppException) as exc_info:
        await _resolve_response_tool_approval(
            response_id=response.id,
            request=_approval_request(),
            payload={"approved": False},
            current_user=SimpleNamespace(id="user-1"),
            db=db,
            approval_id=approval.id,
        )

    assert exc_info.value.http_status == 409
    assert approval.status == "approved"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeated_approved_resolution_requeues_stuck_requires_action_response(
    monkeypatch,
) -> None:
    response = _approval_response("requires_action")
    approval = _approval("approved")
    db = AsyncMock()
    db.scalar.side_effect = [approval, 9]
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._owned_response",
        AsyncMock(return_value=response),
    )
    ensure_outbox = AsyncMock()
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._ensure_approval_resume_outbox",
        ensure_outbox,
    )

    result = await _resolve_response_tool_approval(
        response_id=response.id,
        request=_approval_request(),
        payload={"approved": True},
        current_user=SimpleNamespace(id="user-1"),
        db=db,
        approval_id=approval.id,
    )

    assert result["status"] == "approved"
    assert result["starting_after"] == 9
    assert response.status == "queued"
    ensure_outbox.assert_awaited_once_with(
        db,
        response_id=response.id,
        approval_id="approval-1",
    )
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeated_matching_approval_is_idempotent_without_extra_resume(
    monkeypatch,
) -> None:
    response = _approval_response("queued")
    approval = _approval("approved")
    db = AsyncMock()
    db.scalar.side_effect = [approval, 12]
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._owned_response",
        AsyncMock(return_value=response),
    )
    ensure_outbox = AsyncMock()
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._ensure_approval_resume_outbox",
        ensure_outbox,
    )

    result = await _resolve_response_tool_approval(
        response_id=response.id,
        request=_approval_request(),
        payload={"approved": True},
        current_user=SimpleNamespace(id="user-1"),
        db=db,
        approval_id=approval.id,
    )

    assert result["status"] == "approved"
    assert result["starting_after"] == 12
    ensure_outbox.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeated_rejected_resolution_is_read_only_even_when_response_requires_action(
    monkeypatch,
) -> None:
    response = _approval_response("requires_action")
    approval = _approval("rejected")
    db = AsyncMock()
    db.scalar.side_effect = [approval, 9]
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._owned_response",
        AsyncMock(return_value=response),
    )
    ensure_outbox = AsyncMock()
    monkeypatch.setattr(
        "gateway.api_gateway.routers.response_aux._ensure_approval_resume_outbox",
        ensure_outbox,
    )

    result = await _resolve_response_tool_approval(
        response_id=response.id,
        request=_approval_request(),
        payload={"approved": False},
        current_user=SimpleNamespace(id="user-1"),
        db=db,
        approval_id=approval.id,
    )

    assert result["status"] == "rejected"
    assert result["starting_after"] == 9
    assert response.status == "requires_action"
    ensure_outbox.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_approval_resume_outbox_revives_published_row() -> None:
    existing = SimpleNamespace(
        status="published",
        available_at=None,
        published_at=datetime.now(UTC),
        last_error=None,
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=existing), add=Mock())

    result = await _ensure_approval_resume_outbox(
        db,
        response_id="resp-1",
        approval_id="approval-1",
    )

    assert result is existing
    assert existing.status == "pending"
    assert existing.available_at is not None
    assert existing.published_at is None
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_approval_resume_outbox_revives_failed_row() -> None:
    existing = SimpleNamespace(
        status="failed",
        available_at=None,
        published_at=None,
        last_error="redis down",
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=existing), add=Mock())

    result = await _ensure_approval_resume_outbox(
        db,
        response_id="resp-1",
        approval_id="approval-1",
    )

    assert result is existing
    assert existing.status == "pending"
    assert existing.available_at is not None
    assert existing.published_at is None
    assert existing.last_error is None
    db.add.assert_not_called()


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

    payload = _json_safe(
        {
            "evidence": Evidence(
                content="事实",
                provenance=Provenance(source="test"),
            )
        }
    )
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


def test_deterministic_memory_is_projected_before_response_completion_event() -> None:
    worker = (Path(__file__).resolve().parents[1] / "infra/responses/worker.py").read_text(
        encoding="utf-8"
    )

    projection = worker.index("deterministic_only=True")
    completion = worker.index("event_type=final_event")
    deferred_learning = worker.index("if not deterministic_memory_projected")

    assert projection < completion < deferred_learning


def test_legacy_chat_route_is_explicitly_retired() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "gateway/api_gateway/routers/chat.py").read_text(encoding="utf-8")
    assert "status_code=410" in text
    assert "chat_endpoint_retired" in text


def test_temporary_conversations_expire_and_reject_durable_resource_binding() -> None:
    source = Path(__file__).resolve().parents[1] / "gateway/api_gateway/routers/responses.py"
    text = source.read_text(encoding="utf-8")
    assert "timedelta(days=30)" in text
    assert "timedelta(days=30)" in text


def test_side_effect_tools_disable_both_retry_layers() -> None:
    source = Path(__file__).resolve().parents[1] / "kernel/agent_loop/runner.py"
    text = source.read_text(encoding="utf-8")
    assert "max_retries=spec.max_retries if spec.side_effect == SideEffect.READ else 0" in text
    assert "side_effect_outcome_unknown" in text


def test_tool_spec_preserves_explicit_zero_retry_policy() -> None:
    spec = parse_tool_specs(
        [
            {
                "type": "function",
                "name": "external_write",
                "parameters": {"type": "object", "properties": {}},
                "opentrace": {"side_effect": "write", "max_retries": 0},
            }
        ]
    )[0]
    assert spec.max_retries == 0
