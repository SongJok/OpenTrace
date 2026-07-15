"""
Kernel public exports.

Keep package import lightweight to avoid circular imports during startup.
Consumers that need concrete classes can still import from `kernel`, while the
actual modules are only loaded on first attribute access.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from kernel.protocol.events import (
    CognitiveEventTypeV2,
    CognitiveEventV2,
    SpanStage,
    TraceContext,
)
from kernel.protocol.governance import (
    Budget,
    BudgetTracker,
    GovernanceProfile,
    QualityGate,
    QualityGateResult,
)
from kernel.protocol.mcp import (
    Action,
    ActionPlan,
    AgentTrace,
    CognitiveContext,
    Critique,
    Evidence,
    FailureTag,
    Hypothesis,
)

__all__ = [
    "IntentEngine",
    "Intent",
    "PolicyEngine",
    "Decision",
    "Route",
    "Strategy",
    "ReasoningEngine",
    "ReasoningResult",
    "MetaCognition",
    "ValidationResult",
    # Protocol Layer
    "CognitiveEventV2",
    "CognitiveEventTypeV2",
    "SpanStage",
    "TraceContext",
    "CognitiveContext",
    "Evidence",
    "Hypothesis",
    "ActionPlan",
    "Action",
    "Critique",
    "AgentTrace",
    "FailureTag",
    "GovernanceProfile",
    "Budget",
    "BudgetTracker",
    "QualityGate",
    "QualityGateResult",
]

_EXPORTS = {
    "IntentEngine": ("kernel.intent_engine.engine", "IntentEngine"),
    "Intent": ("kernel.intent_engine.engine", "Intent"),
    "PolicyEngine": ("kernel.policy.engine", "PolicyEngine"),
    "Decision": ("kernel.policy.engine", "Decision"),
    "Route": ("kernel.policy.engine", "Route"),
    "Strategy": ("kernel.policy.engine", "Strategy"),
    "ReasoningEngine": ("kernel.reasoning.engine", "ReasoningEngine"),
    "ReasoningResult": ("kernel.reasoning.engine", "ReasoningResult"),
    "MetaCognition": ("kernel.meta_cognition.meta_cognition", "MetaCognition"),
    "ValidationResult": ("kernel.meta_cognition.meta_cognition", "ValidationResult"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        # Fall back to submodule import (e.g. kernel.orchestrator)
        try:
            mod = import_module(f"kernel.{name}")
            globals()[name] = mod
            return mod
        except ModuleNotFoundError:
            raise AttributeError(f"module 'kernel' has no attribute {name!r}")
    module_name, attr_name = target
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from kernel.intent_engine.engine import Intent, IntentEngine
    from kernel.meta_cognition.meta_cognition import MetaCognition, ValidationResult
    from kernel.policy.engine import Decision, PolicyEngine, Route, Strategy
    from kernel.reasoning.engine import ReasoningEngine, ReasoningResult
