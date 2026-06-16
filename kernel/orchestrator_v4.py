"""
已弃用 — 仅从 legacy.v4 重新导出。请勿扩展。

生产路径：CognitiveKernel → CognitiveSupervisor → RuntimeGateway。
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