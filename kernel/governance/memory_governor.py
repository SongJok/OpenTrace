"""记忆治理 — 注入上限与污染检查。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MemoryGovernanceResult:
    allowed: bool = True
    max_tokens: int = 4096
    warnings: list[str] = field(default_factory=list)


class MemoryGovernor:
    def evaluate_injection(self, token_estimate: int, max_tokens: int = 4096) -> MemoryGovernanceResult:
        if token_estimate > max_tokens:
            return MemoryGovernanceResult(
                allowed=False,
                max_tokens=max_tokens,
                warnings=["memory_injection_exceeds_budget"],
            )
        return MemoryGovernanceResult(allowed=True, max_tokens=max_tokens)