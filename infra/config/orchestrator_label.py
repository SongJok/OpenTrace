"""健康检查与观测用的编排器标签（与 vNext / legacy V4 开关一致）。"""

from __future__ import annotations

from infra.config.settings import Settings


def resolve_orchestrator_label(settings: Settings) -> str:
    """V4 关闭时报告 vnext，避免 /health 仍显示 v4。"""
    if getattr(settings, "kernel_orchestrator_v4_enabled", False):
        return str(getattr(settings, "kernel_orchestrator_version", "v4") or "v4")
    return "vnext"


def orchestrator_annotations_enabled(settings: Settings) -> bool:
    """V4 路径才启用 legacy DAG 注解开关展示。"""
    return bool(getattr(settings, "kernel_orchestrator_v4_enabled", False))