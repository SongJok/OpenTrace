"""RuntimeGateway tier0 entry — static contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_gateway_exposes_try_tier0_chat():
    text = (ROOT / "kernel/runtime_gateway.py").read_text(encoding="utf-8")
    assert "async def try_tier0_chat" in text
    assert "Tier0ChatContext" in text
    assert "kernel.runtime.tier0_paths" in text


def test_responses_does_not_route_via_runtime_gateway():
    text = (ROOT / "gateway/api_gateway/routers/responses.py").read_text(encoding="utf-8")
    assert "runtime_gateway" not in text
    assert "add_outbox" in text


def test_kernel_tier0_ssot_not_gateway_logic():
    gw = (ROOT / "gateway/api_gateway/tier0_paths.py").read_text(encoding="utf-8")
    assert "kernel.runtime.tier0_paths" in gw
    assert "def is_sql_retrieval_intent" not in gw


def test_runtime_gateway_tool_fast_path_entry():
    text = (ROOT / "kernel/runtime_gateway.py").read_text(encoding="utf-8")
    assert "try_tool_fast_path" in text
    assert "stream_tool_fast_path" in text


def test_cognitive_kernel_routes_tool_via_gateway():
    text = (ROOT / "kernel/cognitive_kernel.py").read_text(encoding="utf-8")
    assert "get_runtime_gateway().try_tool_fast_path" in text
    assert "get_runtime_gateway().stream_tool_fast_path" in text
