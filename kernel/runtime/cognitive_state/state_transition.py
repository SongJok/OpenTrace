"""Runtime phase state transitions — shared with behavior_contracts."""

from __future__ import annotations

from kernel.protocol.behavior_contracts import (
    RuntimePhase,
    assert_phase_transition,
    enforce_phase_transition,
)

__all__ = [
    "RuntimePhase",
    "assert_phase_transition",
    "enforce_phase_transition",
]