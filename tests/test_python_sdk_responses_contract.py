"""Python SDK 必须只使用当前 Responses/Conversation 主链路。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_python_sdk_uses_responses_and_typed_sse_events():
    source = (ROOT / "sdk/python_sdk/client.py").read_text(encoding="utf-8")
    assert '"/api/v2/responses"' in source
    assert "/api/v1/chat" not in source
    assert 'event_type == "response.output_text.delta"' in source


def test_python_sdk_sessions_use_canonical_conversation_projection():
    source = (ROOT / "sdk/python_sdk/client.py").read_text(encoding="utf-8")
    assert "/api/v2/conversations/{session_id}/messages" in source
    assert "/api/v2/conversations/{session_id}" in source
    assert "/api/v1/sessions" not in source


def test_conversation_delete_uses_database_cascades_without_loading_legacy_rows():
    source = (ROOT / "gateway/api_gateway/routers/conversations.py").read_text(encoding="utf-8")
    assert "delete(ChatSession).where(ChatSession.id == session.id)" in source
    assert "await db.delete(session)" not in source
