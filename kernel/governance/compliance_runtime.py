"""Compliance runtime — GDPR / SOC2 / HIPAA framework hooks (policy evaluation)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_FRAMEWORK_RULES: dict[str, dict[str, Any]] = {
    "gdpr": {"require_residency_eu_for_pii": True, "block_pii_export": True},
    "soc2": {"require_audit_trace": True},
    "hipaa": {"block_pii_without_baa": True, "require_residency_us": True},
    "pci_dss": {"block_raw_card_data": True},
    "iso27001": {"require_data_classification": True},
}


@dataclass
class ComplianceDecision:
    allowed: bool
    violations: list[str] = field(default_factory=list)
    frameworks_evaluated: list[str] = field(default_factory=list)
    audit_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "violations": list(self.violations),
            "frameworks_evaluated": list(self.frameworks_evaluated),
            "audit_tags": list(self.audit_tags),
        }


class ComplianceRuntime:
    def evaluate_turn(
        self,
        *,
        pii_detected: bool = False,
        data_region: str = "global",
        frameworks: list[str] | None = None,
        raw_payment_data: bool = False,
        audit_trace_present: bool = True,
    ) -> ComplianceDecision:
        fws = [f.lower() for f in (frameworks or ["soc2"])]
        violations: list[str] = []
        tags: list[str] = []
        for fw in fws:
            rules = _FRAMEWORK_RULES.get(fw, {})
            tags.append(f"framework:{fw}")
            if rules.get("block_pii_export") and pii_detected and data_region not in (
                "eu",
                "eea",
                "global",
            ):
                violations.append(f"{fw}_pii_residency")
            if rules.get("require_residency_eu_for_pii") and pii_detected:
                if data_region not in ("eu", "eea"):
                    violations.append(f"{fw}_eu_residency_required")
            if rules.get("block_pii_without_baa") and pii_detected:
                violations.append(f"{fw}_baa_required")
            if rules.get("require_residency_us") and pii_detected and data_region not in (
                "us",
                "global",
            ):
                violations.append(f"{fw}_us_residency_required")
            if rules.get("block_raw_card_data") and raw_payment_data:
                violations.append(f"{fw}_pci_block")
            if rules.get("require_audit_trace") and not audit_trace_present:
                violations.append(f"{fw}_audit_trace_missing")
        return ComplianceDecision(
            allowed=len(violations) == 0,
            violations=violations,
            frameworks_evaluated=fws,
            audit_tags=tags,
        )