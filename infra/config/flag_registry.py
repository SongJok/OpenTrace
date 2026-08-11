"""P0 高影响开关注册表与能力 Profile，作为配置治理单一真相。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FlagPhase = Literal["experimental", "stable", "deprecated"]


@dataclass(frozen=True)
class FlagSpec:
    name: str
    default: bool
    phase: FlagPhase
    owner: str
    introduced: str
    affects: str
    requires: tuple[str, ...] = ()
    exit_criteria: str = ""
    remove_by: str = ""

    def governance_errors(self) -> list[str]:
        errors: list[str] = []
        if self.phase == "experimental":
            if not self.exit_criteria:
                errors.append(f"{self.name}: experimental flag missing exit_criteria")
            if not self.remove_by:
                errors.append(f"{self.name}: experimental flag missing remove_by")
        return errors


# P0 后公开支持的高影响运行时例外开关。Agent 能力组合由 CAPABILITY_PROFILE 管理；
# 旧 Cognitive Runtime 的大量细粒度字段继续兼容读取，但不再进入公开注册表。
KERNEL_FLAG_REGISTRY: tuple[FlagSpec, ...] = (
    FlagSpec(
        "kernel_runtime_phase_transition_strict",
        True,
        "stable",
        "runtime",
        "0.1.0",
        "responses-runtime",
    ),
    FlagSpec(
        "kernel_registry_dispatch_strict",
        True,
        "stable",
        "runtime",
        "0.1.0",
        "tool-dispatch",
    ),
    FlagSpec(
        "kernel_runtime_replay_enabled",
        True,
        "stable",
        "observability",
        "0.1.0",
        "audit-replay",
    ),
    FlagSpec(
        "kernel_agent_runtime_v3_strict",
        False,
        "stable",
        "agent-runtime",
        "0.1.0",
        "agent-contribution-contract",
        ("kernel_agent_runtime_v3_enabled",),
    ),
    FlagSpec(
        "kernel_agent_learning_auto_apply",
        False,
        "experimental",
        "agent-quality",
        "0.1.0",
        "learning",
        ("kernel_capability_intelligence_enabled",),
        "连续两个 Beta 发布中通过回放评测且无越权策略写入",
        "0.3.0",
    ),
    FlagSpec(
        "enterprise_tenant_rls_enabled",
        False,
        "experimental",
        "security",
        "0.1.0",
        "tenant-isolation",
        exit_criteria="核心事实表 RLS 与跨租户负向测试全部进入发布门禁",
        remove_by="0.3.0",
    ),
    FlagSpec(
        "data_agent_source_resolution_enabled",
        True,
        "stable",
        "data-platform",
        "0.2.0",
        "data-agent-source-resolution",
    ),
    FlagSpec(
        "data_agent_learning_enabled",
        True,
        "experimental",
        "data-platform",
        "0.2.0",
        "data-agent-governed-learning",
        exit_criteria="核心业务域 Golden Case 连续两个发布周期无错误晋升或跨 Scope 复用",
        remove_by="0.4.0",
    ),
)


# 企业身份上线控制与 Agent 能力组合分开治理，避免扩大运行时 Flag 面。
ENTERPRISE_CONTROL_REGISTRY: tuple[FlagSpec, ...] = (
    FlagSpec(
        "identity_oidc_enabled",
        False,
        "experimental",
        "security",
        "0.1.0",
        "authentication",
        exit_criteria="完成两个受支持 IdP 的 JWKS、撤销和故障切换互操作认证",
        remove_by="0.3.0",
    ),
)


def validate_registry_governance() -> list[str]:
    return [
        error
        for spec in (*KERNEL_FLAG_REGISTRY, *ENTERPRISE_CONTROL_REGISTRY)
        for error in spec.governance_errors()
    ]


def validate_flag_dependencies(settings: object) -> list[str]:
    """Return violation messages when a flag is on but its requires are off."""
    violations: list[str] = []
    for spec in (*KERNEL_FLAG_REGISTRY, *ENTERPRISE_CONTROL_REGISTRY):
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
    return [name for name, count in Counter(names).items() if count > 1]


def env_var_name_for_flag(flag_name: str) -> str:
    return flag_name.upper()


def env_example_lines_for_registry() -> list[str]:
    lines: list[str] = []
    for spec in (*KERNEL_FLAG_REGISTRY, *ENTERPRISE_CONTROL_REGISTRY):
        env_key = env_var_name_for_flag(spec.name)
        default = "true" if spec.default else "false"
        lines.append(f"{env_key}={default}")
    return lines


def registry_env_keys() -> set[str]:
    return {
        env_var_name_for_flag(spec.name)
        for spec in (*KERNEL_FLAG_REGISTRY, *ENTERPRISE_CONTROL_REGISTRY)
    }
