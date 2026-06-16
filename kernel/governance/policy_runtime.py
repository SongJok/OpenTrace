"""Policy Runtime — mutation-point hooks (plan / evidence / memory / replay)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MutationKind = Literal["plan", "evidence_fusion", "memory_write", "replay_load"]


@dataclass
class PolicyMutationDecision:
    allowed: bool = True
    violations: list[str] = field(default_factory=list)
    guardrails: dict[str, Any] = field(default_factory=dict)


class PolicyRuntime:
    """Embed governance in runtime mutations (not only evaluate/deny at boundaries)."""

    def on_planning(self, ctx: Any) -> PolicyMutationDecision:
        from kernel.governance.cognitive_policy_engine import CognitivePolicyEngine

        md = getattr(ctx, "metadata", None) or {}
        gg = md.get("goal_graph") or {}
        intent = str(getattr(ctx, "task_type", "general") or gg.get("intent_category", "general"))
        sub = max(0, len(gg.get("goals", [])) - 1) if isinstance(gg, dict) else 0
        budget = getattr(ctx, "cognitive_budget", None) or {}
        steps = int(budget.get("max_reasoning_steps", 10) or 10)
        cog = CognitivePolicyEngine().evaluate_planning(
            intent_category=intent,
            sub_goal_count=sub,
            max_steps=steps,
            allowed_capabilities=list(getattr(ctx, "allowed_capabilities", None) or []),
        )
        return PolicyMutationDecision(
            allowed=len(cog.violations) == 0,
            violations=list(cog.violations),
            guardrails={"max_capabilities": cog.max_capabilities},
        )

    def on_evidence_fusion(
        self,
        *,
        evidence_count: int,
        min_required: int = 0,
        hallucination_risk: float = 0.0,
    ) -> PolicyMutationDecision:
        from kernel.governance.evidence_policy_engine import EvidencePolicyEngine

        d = EvidencePolicyEngine().evaluate_fusion(
            evidence_count=evidence_count,
            min_required=min_required,
            hallucination_risk=hallucination_risk,
        )
        return PolicyMutationDecision(
            allowed=d.allow_fusion,
            violations=list(d.violations),
            guardrails={"min_count": d.min_count, "require_rank": d.require_rank},
        )

    def on_memory_write(self, *, proposed_tokens: int, pollution_risk: float = 0.0) -> PolicyMutationDecision:
        from kernel.governance.memory_policy_engine import MemoryPolicyEngine

        d = MemoryPolicyEngine().evaluate_write(
            proposed_tokens=proposed_tokens,
            pollution_risk=pollution_risk,
        )
        return PolicyMutationDecision(
            allowed=d.allow_write,
            violations=list(d.violations),
            guardrails={"max_tokens": d.max_tokens},
        )

    def on_replay_load(self, contract: dict[str, Any]) -> PolicyMutationDecision:
        from kernel.protocol.behavior_contracts import ReplayContract, validate_replay_contract

        rc = ReplayContract(
            request_id=str(contract.get("request_id", "")),
            session_id=str(contract.get("session_id", "")),
            root_goal_id=str(contract.get("root_goal_id", "")),
            artifact_id=str(contract.get("artifact_id", "")),
            evidence_ids=list(contract.get("evidence_ids") or []),
        )
        v = validate_replay_contract(rc)
        return PolicyMutationDecision(allowed=len(v) == 0, violations=v)


def get_policy_runtime() -> PolicyRuntime:
    if not hasattr(get_policy_runtime, "_inst"):
        get_policy_runtime._inst = PolicyRuntime()  # type: ignore[attr-defined]
    return get_policy_runtime._inst  # type: ignore[attr-defined]