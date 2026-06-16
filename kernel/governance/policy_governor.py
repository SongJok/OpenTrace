"""策略治理 — 执行策略门禁。"""

from __future__ import annotations

from dataclasses import dataclass, field

from kernel.protocol.runtime_contract import ExecutionPolicy

@dataclass
class PolicyGovernanceResult:
    allowed: bool = True
    violations: list[str] = field(default_factory=list)

class PolicyGovernor:
    def evaluate(self, policy: ExecutionPolicy) -> PolicyGovernanceResult:
        violations: list[str] = []
        if policy.sandbox_required and not policy.capability_executor_mode:
            violations.append("sandbox_requires_capability_executor")
        return PolicyGovernanceResult(allowed=len(violations) == 0, violations=violations)