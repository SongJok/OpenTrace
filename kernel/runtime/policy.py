"""
UnifiedPolicyEngine — Converge routing policy, safety guardrails, and
permission checks into a single policy evaluation pipeline.

Currently, these checks are scattered across:
  - chat.py (L1000-1180): risk assessment, tool_permission_token
  - Responses Agent Loop: input guardrails
  - Various ad-hoc guards

The UnifiedPolicyEngine provides a single `.evaluate(ctx) → PolicyDecision`
entry point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PolicyRule:
    """A single policy rule with a condition and action."""

    name: str
    description: str
    priority: int = 0  # higher = evaluated first
    condition: str = ""  # human-readable condition description
    action: str = "allow"  # allow | deny | warn | require_confirmation

    def evaluate(self, ctx: dict[str, Any]) -> tuple[bool, str]:
        """Return (matched, reason). Subclass for programmatic rules."""
        return False, ""


@dataclass
class PolicyDecision:
    """Result of policy evaluation."""

    allowed: bool = True
    risk_level: str = "low"  # low | medium | high | critical
    reason: str = ""
    requires_confirmation: bool = False
    denied_rules: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class UnifiedPolicyEngine:
    """Central policy evaluation for all requests.

    Evaluates rules in priority order. First deny stops evaluation.
    """

    def __init__(self) -> None:
        self._rules: list[PolicyRule] = []

    def register(self, rule: PolicyRule) -> None:
        self._rules.append(rule)
        self._rules.sort(key=lambda r: -r.priority)
        logger.debug("Policy rule registered", name=rule.name, action=rule.action)

    async def evaluate(self, ctx: Any) -> PolicyDecision:  # RuntimeContext
        """Evaluate all rules against the given context."""
        decision = PolicyDecision()

        for rule in self._rules:
            matched, reason = rule.evaluate(ctx)
            if not matched:
                continue

            if rule.action == "deny":
                decision.allowed = False
                decision.risk_level = "critical"
                decision.denied_rules.append(rule.name)
                decision.reason = reason
                return decision

            if rule.action == "require_confirmation":
                decision.requires_confirmation = True
                decision.warnings.append(f"{rule.name}: {reason}")
                if decision.risk_level != "critical":
                    decision.risk_level = "high"

            if rule.action == "warn":
                decision.warnings.append(f"{rule.name}: {reason}")

        if not decision.allowed:
            decision.reason = decision.reason or "Policy denied"
        elif decision.requires_confirmation:
            decision.reason = "Requires user confirmation"
        else:
            decision.reason = "ok"

        return decision


# Module-level singleton — follow capability_registry pattern
policy_engine = UnifiedPolicyEngine()
