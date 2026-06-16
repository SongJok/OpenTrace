"""Governors have a single implementation in kernel.governance; governance/* re-exports."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_GOVERNOR_REEXPORTS = [
    "governance/runtime_governor.py",
    "governance/audit_governor.py",
    "governance/capability_governor.py",
    "governance/evidence_governor.py",
    "governance/memory_governor.py",
    "governance/risk_governor.py",
    "governance/policy_governor.py",
    "governance/prompt_governor.py",
]


def test_governance_runtime_governor_is_kernel_class():
    from governance.runtime_governor import RuntimeGovernor as TopRuntime
    from kernel.governance.runtime_governor import RuntimeGovernor as KernelRuntime

    assert TopRuntime is KernelRuntime


def test_governance_audit_governor_is_kernel_class():
    from governance.audit_governor import AuditGovernor as TopAudit
    from kernel.governance.audit_governor import AuditGovernor as KernelAudit

    assert TopAudit is KernelAudit


def test_governance_prompt_governor_is_kernel_class():
    from governance.prompt_governor import PromptGovernor as TopPrompt
    from kernel.governance.prompt_governor import PromptGovernor as KernelPrompt

    assert TopPrompt is KernelPrompt


def test_governance_center_uses_kernel_governors():
    from kernel.governance.governance_center import GovernanceCenter
    from kernel.governance.runtime_governor import RuntimeGovernor

    gc = GovernanceCenter()
    assert isinstance(gc.runtime, RuntimeGovernor)


def test_governance_center_compliance_failure_records_degradation(monkeypatch):
    from kernel.governance.governance_center import GovernanceCenter

    class _BrokenCompliance:
        def evaluate_turn(self, **kwargs):
            raise RuntimeError("compliance_unavailable")

    monkeypatch.setattr(
        "kernel.governance.compliance_runtime.ComplianceRuntime",
        lambda: _BrokenCompliance(),
    )
    bundle = GovernanceCenter().evaluate_turn(
        evidence_count=1,
        fusion_confidence=0.9,
        hallucination_risk=0.1,
        critic_passed=True,
        route="test",
    )
    obs = bundle.semantic_observability
    assert isinstance(obs, dict)
    assert "compliance_runtime" not in obs
    deg = obs.get("degradations") or []
    assert any(d.get("subsystem") == "compliance_runtime" for d in deg)


def test_governance_top_level_governor_modules_are_reexport_only():
    """Prevent re-introducing duplicate governor implementations under governance/."""
    for rel in _GOVERNOR_REEXPORTS:
        path = ROOT / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        class_defs = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
        assert class_defs == [], f"{rel} must not define classes: {class_defs}"
        imports_kernel = any(
            isinstance(n, ast.ImportFrom) and (n.module or "").startswith("kernel.governance")
            for n in tree.body
        )
        assert imports_kernel, f"{rel} must import from kernel.governance"


_POLICY_ENGINE_REEXPORTS = [
    "governance/cognitive_policy_engine.py",
    "governance/runtime_policy_engine.py",
    "governance/evidence_policy_engine.py",
    "governance/memory_policy_engine.py",
    "governance/execution_guardrails.py",
    "governance/semantic_metrics_pipeline.py",
    "governance/adaptive_risk_engine.py",
]


def test_policy_engine_modules_are_reexport_only():
    for rel in _POLICY_ENGINE_REEXPORTS:
        path = ROOT / rel
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        class_defs = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
        assert class_defs == [], f"{rel} must not define classes: {class_defs}"


def test_policy_engines_reexport_is_kernel():
    from governance.evidence_policy_engine import EvidencePolicyEngine as top_e
    from kernel.governance.evidence_policy_engine import EvidencePolicyEngine as kernel_e

    assert top_e is kernel_e

    from governance.memory_policy_engine import MemoryPolicyEngine as top_m
    from kernel.governance.memory_policy_engine import MemoryPolicyEngine as kernel_m

    assert top_m is kernel_m

    from governance.execution_guardrails import ExecutionGuardrails as top_g
    from kernel.governance.execution_guardrails import ExecutionGuardrails as kernel_g

    assert top_g is kernel_g

    from governance.cognitive_policy_engine import CognitivePolicyEngine as top_c
    from kernel.governance.cognitive_policy_engine import CognitivePolicyEngine as kernel_c

    assert top_c is kernel_c


def test_semantic_alerts_reexport_is_kernel():
    from governance.semantic_alerts import export_turn_observability as top_export
    from kernel.governance.semantic_alerts import export_turn_observability as kernel_export

    assert top_export is kernel_export


def test_semantic_health_single_compute_path():
    from governance.semantic_metrics import compute_cognitive_health
    from governance.semantic_metrics_pipeline import SemanticMetricsPipeline

    snap = compute_cognitive_health(
        evidence_count=2,
        fusion_confidence=0.8,
        hallucination_risk=0.1,
        critic_passed=True,
    )
    recorded = SemanticMetricsPipeline().record_turn(
        "s-contract",
        evidence_count=2,
        fusion_confidence=0.8,
        hallucination_risk=0.1,
        critic_passed=True,
    )
    assert recorded.evidence_integrity == snap.evidence_integrity