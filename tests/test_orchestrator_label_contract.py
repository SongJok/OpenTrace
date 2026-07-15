"""编排器健康检查标签 — vNext 默认时不得误报 v4。"""

from __future__ import annotations

from infra.config.orchestrator_label import (
    orchestrator_annotations_enabled,
    resolve_orchestrator_label,
)
from infra.config.settings import Settings


def test_runtime_reports_unified_responses_agent_loop():
    s = Settings(
        app_env="development",
        gateway_port=14100,
        app_port=14100,
    )
    assert resolve_orchestrator_label(s) == "responses-agent-loop"
    assert orchestrator_annotations_enabled(s) is False
