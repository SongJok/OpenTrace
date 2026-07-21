"""Chat session tenant columns on ORM."""

from __future__ import annotations

from infra.storage.models import ChatSession


def test_chat_session_has_tenant_columns():
    cols = {c.key for c in ChatSession.__table__.columns}
    assert "tenant_id" in cols
    assert "org_id" in cols
    assert "workspace_id" in cols


def test_responses_record_persists_tenant_boundary():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "gateway/api_gateway/routers/responses.py").read_text(
        encoding="utf-8"
    )
    assert "tenant_id=tenant_id" in text
    assert "workspace_id=workspace_id" in text
