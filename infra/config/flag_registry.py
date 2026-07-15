"""Kernel feature-flag registry — dependencies and phase labels for enterprise config governance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

FlagPhase = Literal["experimental", "stable", "deprecated"]


@dataclass(frozen=True)
class FlagSpec:
    name: str
    default: bool
    phase: FlagPhase = "stable"
    requires: tuple[str, ...] = ()
    affects: str = "runtime"


# Subset of high-impact kernel flags (extend in CI contract tests).
KERNEL_FLAG_REGISTRY: tuple[FlagSpec, ...] = (
    FlagSpec(
        "kernel_runtime_phase_transition_strict",
        False,
        "stable",
        affects="runtime",
    ),
    FlagSpec(
        "kernel_cognitive_state_persist_enabled",
        False,
        "stable",
        affects="runtime",
    ),
    FlagSpec(
        "kernel_staging_phase_transition_strict",
        False,
        "stable",
        ("kernel_runtime_phase_transition_strict",),
        affects="runtime",
    ),
    FlagSpec("kernel_refine_replan_enabled", True, "stable", affects="planning"),
    FlagSpec("kernel_memory_fabric_primary_only", False, "stable", affects="memory"),
    FlagSpec("kernel_runtime_replay_enabled", False, "experimental", affects="replay"),
    FlagSpec(
        "kernel_agent_runtime_v3_enabled",
        True,
        "stable",
        affects="agent_runtime",
    ),
    FlagSpec(
        "kernel_agent_runtime_v3_strict",
        False,
        "stable",
        ("kernel_agent_runtime_v3_enabled",),
        affects="agent_runtime",
    ),
    FlagSpec(
        "kernel_unified_evidence_strict",
        False,
        "stable",
        ("kernel_agent_runtime_v3_enabled",),
        affects="evidence",
    ),
    FlagSpec("kernel_web_intelligence_preferred", True, "stable", affects="routing"),
    FlagSpec(
        "kernel_capability_intelligence_enabled",
        True,
        "stable",
        affects="capability_intelligence",
    ),
    FlagSpec(
        "kernel_agent_learning_auto_apply",
        False,
        "experimental",
        ("kernel_capability_intelligence_enabled",),
        affects="capability_intelligence",
    ),
    FlagSpec(
        "enterprise_quota_redis_enabled",
        False,
        "experimental",
        affects="control_plane",
    ),
    FlagSpec(
        "enterprise_usage_redis_enabled",
        False,
        "experimental",
        affects="control_plane",
    ),
    FlagSpec(
        "kernel_world_model_cross_process_enabled",
        False,
        "experimental",
        affects="world_model",
    ),
)


def validate_flag_dependencies(settings: object) -> list[str]:
    """Return violation messages when a flag is on but its requires are off."""
    violations: list[str] = []
    for spec in KERNEL_FLAG_REGISTRY:
        if not getattr(settings, spec.name, spec.default):
            continue
        for req in spec.requires:
            if not getattr(settings, req, False):
                violations.append(f"{spec.name}_requires_{req}")
    return violations


def duplicate_settings_field_names(settings_cls: type) -> list[str]:
    """Detect duplicate field names on Settings model (Pydantic last-wins silently)."""
    from collections import Counter

    names = list(getattr(settings_cls, "model_fields", {}).keys())
    return [n for n, c in Counter(names).items() if c > 1]


def env_var_name_for_flag(flag_name: str) -> str:
    return flag_name.upper()


def env_example_lines_for_registry() -> list[str]:
    """Suggested .env.example lines for KERNEL_FLAG_REGISTRY (idempotent append)."""
    lines: list[str] = []
    for spec in KERNEL_FLAG_REGISTRY:
        env_key = env_var_name_for_flag(spec.name)
        default = "true" if spec.default else "false"
        lines.append(f"{env_key}={default}")
    return lines


def registry_env_keys() -> set[str]:
    return {env_var_name_for_flag(s.name) for s in KERNEL_FLAG_REGISTRY}
