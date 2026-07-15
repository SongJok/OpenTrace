"""Canonical chat entry is the durable Responses worker path."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT_PY = ROOT / "gateway/api_gateway/routers/chat.py"


def test_legacy_chat_is_only_a_migration_tombstone():
    text = CHAT_PY.read_text(encoding="utf-8")
    assert "status_code=410" in text
    assert "chat_endpoint_retired" in text
    assert "CognitiveKernel" not in text


def test_responses_api_only_persists_and_enqueues():
    text = (ROOT / "gateway/api_gateway/routers/responses.py").read_text(encoding="utf-8")
    assert "add_outbox" in text
    assert "AgentLoop" not in text


def test_worker_owns_the_single_agent_loop():
    text = (ROOT / "infra/responses/worker.py").read_text(encoding="utf-8")
    assert "AgentLoop" in text
    assert "claim_response" in text
