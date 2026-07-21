"""Execution-phase guardrails (capability dispatch, timeouts) — canonical."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionGuardrailDecision:
    allowed: bool = True
    violations: list[str] = field(default_factory=list)
    timeout_sec: int = 30


class ExecutionGuardrails:
    def evaluate_dispatch(
        self,
        capability_type: str,
        *,
        allowed_list: list[str] | None = None,
        disallowed_list: list[str] | None = None,
        timeout_sec: int = 30,
    ) -> ExecutionGuardrailDecision:
        violations: list[str] = []
        cap = (capability_type or "").strip()
        allowed = set(allowed_list or [])
        disallowed = set(disallowed_list or [])
        if disallowed and cap in disallowed:
            violations.append(f"capability_disallowed:{cap}")
        if allowed and cap and cap not in allowed:
            violations.append(f"capability_not_in_allowlist:{cap}")
        return ExecutionGuardrailDecision(
            allowed=len(violations) == 0,
            violations=violations,
            timeout_sec=timeout_sec,
        )

    def evaluate_plan(
        self,
        capability_names: list[str],
        *,
        allowed_list: list[str] | None = None,
        disallowed_list: list[str] | None = None,
        timeout_sec: int = 30,
    ) -> ExecutionGuardrailDecision:
        all_v: list[str] = []
        for name in capability_names:
            d = self.evaluate_dispatch(
                name,
                allowed_list=allowed_list,
                disallowed_list=disallowed_list,
                timeout_sec=timeout_sec,
            )
            all_v.extend(d.violations)
        return ExecutionGuardrailDecision(
            allowed=len(all_v) == 0,
            violations=all_v,
            timeout_sec=timeout_sec,
        )