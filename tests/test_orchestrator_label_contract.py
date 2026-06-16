"""编排器健康检查标签 — vNext 默认时不得误报 v4。"""

from __future__ import annotations

from infra.config.orchestrator_label import (
    orchestrator_annotations_enabled,
    resolve_orchestrator_label,
)
from infra.config.settings import Settings


def test_vnext_default_reports_vnext_label():
    s = Settings(
        app_env="development",
        kernel_orchestrator_v4_enabled=False,
        kernel_orchestrator_version="v4",
        gateway_port=14100,
        app_port=14100,
    )
    assert resolve_orchestrator_label(s) == "vnext"
    assert orchestrator_annotations_enabled(s) is False


def test_v4_enabled_reports_version_field():
    s = Settings(
        app_env="development",
        kernel_orchestrator_v4_enabled=True,
        kernel_orchestrator_version="v4",
        gateway_port=14100,
        app_port=14100,
    )
    assert resolve_orchestrator_label(s) == "v4"
    assert orchestrator_annotations_enabled(s) is True