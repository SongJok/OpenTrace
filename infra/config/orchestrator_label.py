"""健康检查与观测用的统一 Responses 编排器标签。"""

from __future__ import annotations

from infra.config.settings import Settings


def resolve_orchestrator_label(settings: Settings) -> str:
    del settings
    return "responses-agent-loop"


def orchestrator_annotations_enabled(settings: Settings) -> bool:
    del settings
    return False
