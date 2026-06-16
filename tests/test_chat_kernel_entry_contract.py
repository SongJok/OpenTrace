"""Chat API main path — kernel entry + tier0 SSOT (static contract)."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT_PY = ROOT / "gateway/api_gateway/routers/chat.py"


def test_chat_main_uses_cognitive_kernel_not_orchestrator_v4_for_stream():
    text = CHAT_PY.read_text(encoding="utf-8")
    assert "_get_kernel()" in text
    assert "CognitiveKernel" in text or "kernel.cognitive_kernel" in text
    assert "kernel.stream(kernel_request)" in text or "kernel.stream(" in text


def test_chat_resume_uses_runtime_gateway_path():
    text = CHAT_PY.read_text(encoding="utf-8")
    assert "resume_turn_via_gateway" in text
    assert "CognitiveOrchestrator" not in text


def test_chat_tier0_imports_single_ssot():
    text = CHAT_PY.read_text(encoding="utf-8")
    assert "try_tier0_chat" in text
    assert "stream_tier0_events" in text
    assert "gateway.api_gateway.tier0_paths" in text or "kernel.runtime_gateway" in text