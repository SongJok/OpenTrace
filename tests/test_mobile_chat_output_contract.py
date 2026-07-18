from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_chat_keeps_full_message_width_on_mobile() -> None:
    chat_page = (ROOT / "frontend/src/pages/ChatPage.tsx").read_text(encoding="utf-8")
    sidebar = (ROOT / "frontend/src/components/Sidebar.tsx").read_text(encoding="utf-8")
    chat_message = (ROOT / "frontend/src/components/ChatMessage.tsx").read_text(encoding="utf-8")

    assert 'aria-label="打开会话侧栏"' in chat_page
    assert "mobileOpen={mobileSidebarOpen}" in chat_page
    assert "max-md:fixed" in sidebar
    assert "mobileOpen ? 'max-md:flex' : 'max-md:hidden'" in sidebar
    assert 'aria-label="关闭会话侧栏"' in sidebar
    assert "opacity-100 transition-opacity sm:opacity-0" in chat_message
