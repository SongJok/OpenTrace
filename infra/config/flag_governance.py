"""Feature-flag dependency registry and validation (enterprise config hygiene)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# When master flag is True, these must also be True (or violations reported).
FLAG_REQUIRES: dict[str, tuple[str, ...]] = {
    "kernel_capability_intelligence_phase2_enabled": (
        "kernel_capability_intelligence_enabled",
    ),
    "kernel_capability_knowledge_graph_enabled": (
        "kernel_capability_intelligence_phase2_enabled",
    ),
    "kernel_capability_reasoner_enabled": (
        "kernel_capability_intelligence_phase2_enabled",
    ),
    "kernel_capability_execution_memory_enabled": (
        "kernel_capability_intelligence_phase2_enabled",
    ),
    "kernel_capability_strategy_memory_enabled": (
        "kernel_capability_intelligence_phase2_enabled",
    ),
    "kernel_capability_evolution_enabled": (
        "kernel_capability_intelligence_phase2_enabled",
    ),
    "kernel_runtime_cognitive_planner_enabled": (
        "kernel_runtime_understanding_enabled",
    ),
    "kernel_runtime_evidence_fusion_critic_enabled": (
        "kernel_runtime_capability_graph_enabled",
    ),
    "kernel_cognitive_planner_v2_enabled": (
        "kernel_runtime_cognitive_planner_enabled",
    ),
    "kernel_memory_graph_redis_enabled": (
        "kernel_memory_fabric_retrieval_enabled",
    ),
    "kernel_memory_fabric_primary_only": (
        "kernel_memory_fabric_retrieval_enabled",
    ),
    "kernel_data_intelligence_routing_enabled": (
        "kernel_agent_data_enabled",
    ),
    "kernel_agent_capability_executor_mode": (
        "kernel_runtime_capability_graph_enabled",
    ),
}

# Mutually exclusive or deprecated combinations.
FLAG_CONFLICTS: list[tuple[str, str, str]] = []


@dataclass
class FlagValidationResult:
    ok: bool
    violations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "violations": list(self.violations)}


def validate_feature_flags(settings: Any) -> FlagValidationResult:
    """Validate flag dependencies against a Settings-like object."""
    violations: list[str] = []

    def _get(name: str) -> bool:
        return bool(getattr(settings, name, False))

    for dependent, requirements in FLAG_REQUIRES.items():
        if not _get(dependent):
            continue
        for req in requirements:
            if not _get(req):
                violations.append(f"flag_requires:{dependent}->requires:{req}")

    for a, b, reason in FLAG_CONFLICTS:
        if _get(a) and _get(b):
            violations.append(f"flag_conflict:{a}+{b}:{reason}")

    if _get("kernel_registry_dispatch_strict") and not _get("kernel_agent_capability_executor_mode"):
        violations.append(
            "flag_requires:kernel_registry_dispatch_strict->requires:kernel_agent_capability_executor_mode"
        )

    return FlagValidationResult(ok=len(violations) == 0, violations=violations)


def export_effective_runtime_flags(settings: Any) -> dict[str, bool]:
    """Snapshot of kernel runtime flags for audit / replay metadata."""
    keys = sorted(
        k
        for k in dir(settings)
        if k.startswith("kernel_") and k.endswith("_enabled")
    )
    return {k: bool(getattr(settings, k, False)) for k in keys}
