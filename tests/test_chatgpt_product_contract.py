from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_response_versions_and_execution_profiles_are_exposed():
    text = (ROOT / "gateway/api_gateway/routers/responses.py").read_text()
    assert 'execution_profile: str = Field(default="auto"' in text
    assert 'execution_mode: str = Field(default="auto"' in text
    assert '@router.post("/responses/{response_id}/retry")' in text
    assert '@router.get("/responses/{response_id}/siblings")' in text


def test_conversations_cover_temporary_and_safe_sharing():
    text = (ROOT / "gateway/api_gateway/routers/conversations.py").read_text()
    assert "is_temporary" in text
    assert "expires_at" in text
    assert '@router.post("/conversations/{conversation_id}/share")' in text
    assert '@router.get("/shared/{public_id}/{token}")' in text
    assert "临时聊天不能分享" in text


def test_frontend_has_profile_picker_and_public_share_route():
    chat = (ROOT / "frontend/src/pages/ChatPage.tsx").read_text()
    app = (ROOT / "frontend/src/App.tsx").read_text()
    assert "opentrace:execution-profile" in chat
    assert "apiCreateConversationShare" in chat
    assert '/share/:publicId/:token' in app
