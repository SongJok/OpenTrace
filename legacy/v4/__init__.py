"""
V4 遗留命名空间 — 生产环境使用 RuntimeGateway + CognitiveSupervisor。

实现位于 legacy.v4.orchestrator（自 kernel/orchestrator_v4.py 迁出）。
"""

from __future__ import annotations

from legacy.v4.orchestrator import (
    CognitiveOrchestratorV4,
    OrchestratorV4Request,
    OrchestratorV4Response,
    VALID_FORCE_MODES,
)

__all__ = [
    "CognitiveOrchestratorV4",
    "OrchestratorV4Request",
    "OrchestratorV4Response",
    "VALID_FORCE_MODES",
]