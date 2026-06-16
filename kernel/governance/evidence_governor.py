"""证据治理 — 完整性与最低证据策略。"""

from __future__ import annotations

from dataclasses import dataclass, field

from kernel.protocol.governance import QualityGate, QualityGateResult
from kernel.protocol.runtime_contract import EvidencePolicy


@dataclass
class EvidenceGovernanceResult:
    passed: bool = True
    failures: list[str] = field(default_factory=list)


class EvidenceGovernor:
    def __init__(self, gate: QualityGate | None = None) -> None:
        self._gate = gate or QualityGate()

    def evaluate(
        self,
        evidence_count: int,
        confidence: float,
        policy: EvidencePolicy | None = None,
    ) -> EvidenceGovernanceResult:
        ep = policy or EvidencePolicy()
        failures: list[str] = []
        if evidence_count < max(ep.min_evidence_count, self._gate.min_evidence_count):
            failures.append("insufficient_evidence")
        if confidence < self._gate.min_confidence:
            failures.append("low_confidence")
        return EvidenceGovernanceResult(passed=len(failures) == 0, failures=failures)

    def to_quality_result(self, result: EvidenceGovernanceResult) -> QualityGateResult:
        return QualityGateResult(
            passed=result.passed,
            score=1.0 if result.passed else 0.0,
            failures=list(result.failures),
        )