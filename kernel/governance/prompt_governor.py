"""提示词治理 — 审计用快照版本管理。"""

from __future__ import annotations

from dataclasses import dataclass, field

@dataclass
class PromptGovernanceResult:
    allowed: bool = True
    snapshot_id: str = ""
    violations: list[str] = field(default_factory=list)

class PromptGovernor:
    def register_snapshot(self, phase: str, content_hash: str) -> PromptGovernanceResult:
        return PromptGovernanceResult(
            allowed=True,
            snapshot_id=f"{phase}:{content_hash[:16]}",
        )