"""
V4 compatibility shim — production must use RuntimeGateway only.

Prefer: from legacy.v4 import CognitiveOrchestratorV4
"""

from __future__ import annotations

from legacy.v4 import (
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