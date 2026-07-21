"""治理中心统一入口 — 汇总语义可观测性。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from kernel.governance.audit_governor import AuditGovernor
from kernel.governance.capability_governor import CapabilityGovernor
from kernel.governance.evidence_governor import EvidenceGovernor
from kernel.governance.memory_governor import MemoryGovernor
from kernel.governance.policy_governor import PolicyGovernor
from kernel.governance.risk_governor import RiskGovernanceResult, RiskGovernor
from kernel.governance.runtime_governor import RuntimeGovernor
from kernel.protocol.runtime_contract import EvidencePolicy, RuntimeTask

@dataclass
class TurnGovernanceBundle:
    runtime: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    semantic_observability: dict[str, Any] = field(default_factory=dict)

class GovernanceCenter:
    def __init__(self) -> None:
        self.runtime = RuntimeGovernor()
        self.evidence = EvidenceGovernor()
        self.risk = RiskGovernor()
        self.capability = CapabilityGovernor()
        self.memory = MemoryGovernor()
        self.policy = PolicyGovernor()
        self.audit = AuditGovernor()

    def evaluate_task(self, task: RuntimeTask) -> TurnGovernanceBundle:
        rt = self.runtime.evaluate_task(task)
        return TurnGovernanceBundle(
            runtime={"allowed": rt.allowed, "violations": list(rt.violations)},
        )

    def evaluate_planning_mutation(self, ctx: Any) -> dict[str, Any]:
        from kernel.governance.policy_runtime import get_policy_runtime

        d = get_policy_runtime().on_planning(ctx)
        return {"allowed": d.allowed, "violations": list(d.violations), "guardrails": d.guardrails}

    def evaluate_memory_mutation(self, *, proposed_tokens: int, pollution_risk: float = 0.0) -> dict[str, Any]:
        from kernel.governance.policy_runtime import get_policy_runtime

        d = get_policy_runtime().on_memory_write(
            proposed_tokens=proposed_tokens,
            pollution_risk=pollution_risk,
        )
        return {"allowed": d.allowed, "violations": list(d.violations), "guardrails": d.guardrails}

    def evaluate_evidence_fusion_mutation(
        self,
        *,
        evidence_count: int,
        min_required: int = 0,
        hallucination_risk: float = 0.0,
    ) -> dict[str, Any]:
        from kernel.governance.policy_runtime import get_policy_runtime

        d = get_policy_runtime().on_evidence_fusion(
            evidence_count=evidence_count,
            min_required=min_required,
            hallucination_risk=hallucination_risk,
        )
        return {"allowed": d.allowed, "violations": list(d.violations), "guardrails": d.guardrails}

    def evaluate_replay_mutation(self, contract: dict[str, Any]) -> dict[str, Any]:
        from kernel.governance.policy_runtime import get_policy_runtime

        d = get_policy_runtime().on_replay_load(contract)
        return {"allowed": d.allowed, "violations": list(d.violations), "guardrails": d.guardrails}

    def evaluate_turn(
        self,
        *,
        evidence_count: int,
        fusion_confidence: float,
        hallucination_risk: float,
        critic_passed: bool | None,
        route: str,
        min_evidence: int = 0,
        replanned: bool = False,
        refine_reexec: bool = False,
        sub_goal_count: int = 0,
        goal_transition_rejected: bool = False,
        adaptive_risk_level: str = "",
        adaptive_risk_score: float = 0.0,
    ) -> TurnGovernanceBundle:
        from kernel.governance.adaptive_risk_engine import AdaptiveRiskEngine

        eg = self.evidence.evaluate(
            evidence_count=evidence_count,
            confidence=fusion_confidence,
            policy=EvidencePolicy(min_evidence_count=min_evidence),
        )
        rg = self.risk.assess(hallucination_risk=hallucination_risk, policy_denied=False)
        ar = AdaptiveRiskEngine().score_turn(
            hallucination_risk=hallucination_risk,
            replanned=replanned,
            evidence_count=evidence_count,
            sub_goal_count=sub_goal_count,
        )
        if adaptive_risk_score > 0:
            ar.score = max(ar.score, adaptive_risk_score)
            if adaptive_risk_level:
                ar.level = adaptive_risk_level
        if ar.level == "high" and not rg.blocked:
            rg = RiskGovernanceResult(
                level="high",
                blocked=rg.blocked,
                signals=list(rg.signals) + list(ar.factors),
            )
        elif ar.level == "medium" and rg.level == "low":
            rg = RiskGovernanceResult(
                level="medium",
                blocked=rg.blocked,
                signals=list(rg.signals) + list(ar.factors),
            )
        snap = self.audit.capture_turn(
            route=route,
            evidence_count=evidence_count,
            critic_passed=critic_passed,
            hallucination_risk=hallucination_risk,
        )
        from kernel.governance.semantic_metrics import compute_cognitive_health

        health = compute_cognitive_health(
            evidence_count=evidence_count,
            fusion_confidence=fusion_confidence,
            hallucination_risk=hallucination_risk,
            critic_passed=critic_passed,
            replanned=replanned,
            refine_reexec=refine_reexec,
            sub_goal_count=sub_goal_count,
            goal_transition_rejected=goal_transition_rejected,
        )
        sem_obs = {
            **asdict(snap),
            "cognitive_health": health.to_dict(),
            "adaptive_risk": {"level": ar.level, "score": ar.score, "factors": list(ar.factors)},
        }
        try:
            from kernel.governance.compliance_runtime import ComplianceRuntime

            comp = ComplianceRuntime().evaluate_turn(
                audit_trace_present=True,
                frameworks=["soc2"],
            )
            sem_obs["compliance_runtime"] = comp.to_dict()
        except Exception as exc:
            from infra.observability.runtime_degraded import append_turn_degradation

            append_turn_degradation(
                sem_obs,
                subsystem="compliance_runtime",
                detail="evaluate_turn",
                exc=exc,
            )
        return TurnGovernanceBundle(
            evidence={"passed": eg.passed, "failures": list(eg.failures)},
            risk={"level": rg.level, "blocked": rg.blocked, "signals": list(rg.signals)},
            semantic_observability=sem_obs,
        )

def get_governance_center() -> GovernanceCenter:
    if not hasattr(get_governance_center, "_g"):
        get_governance_center._g = GovernanceCenter()  # type: ignore[attr-defined]
    return get_governance_center._g  # type: ignore[attr-defined]