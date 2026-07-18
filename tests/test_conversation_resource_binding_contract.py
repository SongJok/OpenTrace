from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from gateway.api_gateway.routers.conversations import (
    UpdateConversationRequest,
    _active_chain,
    _validate_conversation_bindings,
)
from infra.errors import AppException

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_conversation_rejects_unowned_project_binding() -> None:
    db = AsyncMock()
    db.scalar.return_value = None

    with pytest.raises(AppException):
        await _validate_conversation_bindings(
            db,
            user_id="user-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            project_id="project-other",
            assistant_profile_id=None,
        )


@pytest.mark.asyncio
async def test_conversation_accepts_owned_project_and_profile_bindings() -> None:
    db = AsyncMock()
    db.scalar.side_effect = ["project-1", "profile-1"]

    await _validate_conversation_bindings(
        db,
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        project_id="project-1",
        assistant_profile_id="profile-1",
    )

    assert db.scalar.await_count == 2


def test_explicit_null_binding_is_distinct_from_omitted_binding() -> None:
    omitted = UpdateConversationRequest(title="保留现有绑定")
    cleared = UpdateConversationRequest(project_id=None, assistant_profile_id=None)

    assert "project_id" not in omitted.model_fields_set
    assert "assistant_profile_id" not in omitted.model_fields_set
    assert {"project_id", "assistant_profile_id"}.issubset(cleared.model_fields_set)


@pytest.mark.asyncio
async def test_branch_chain_override_does_not_mutate_source_conversation() -> None:
    db = AsyncMock()
    db.scalar.return_value = None
    session = type(
        "Session",
        (),
        {"id": "conversation-1", "active_response_id": "response-current"},
    )()

    chain = await _active_chain(
        db,
        session,
        "user-1",
        starting_response_id="response-branch-point",
    )

    assert chain == []
    assert session.active_response_id == "response-current"


def test_branch_flushes_each_response_before_copying_items() -> None:
    source = (ROOT / "gateway/api_gateway/routers/conversations.py").read_text(encoding="utf-8")
    branch_source = source.split("async def branch_conversation(", 1)[1]

    assert "db.add(copied_response)" in branch_source
    assert branch_source.index("await db.flush()") < branch_source.index(
        "for copied_sequence, source_item"
    )


def test_conversation_delete_rejects_in_flight_response_cascade() -> None:
    source = (ROOT / "gateway/api_gateway/routers/conversations.py").read_text(encoding="utf-8")
    delete_source = source.split("async def delete_conversation(", 1)[1].split(
        '\n\n@router.patch("/messages/{message_id}")', 1
    )[0]

    assert 'ResponseRecord.status.in_(("queued", "in_progress"))' in delete_source
    assert "ResponseRecord.lease_owner.isnot(None)" in delete_source
    assert "ErrorCodes.RESOURCE_EXISTS.code" in delete_source
