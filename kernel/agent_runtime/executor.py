"""AgentRuntimeExecutor — execute agents and return AgentContribution (+ strict mode)."""

from __future__ import annotations

import time
from typing import Any

from agents.base import AgentResult, BaseAgent, TaskMessage
from infra.config.settings import settings
from infra.observability.logger import get_logger
from kernel.agent_runtime.contribution import AgentContribution, contribution_from_agent_result
from kernel.agent_runtime.runtime_contribution import RuntimeContribution, runtime_contribution_from_agent_result
from kernel.agent_runtime.manifest import get_manifest
from kernel.agent_runtime.unified_evidence import publish_unified_to_bus

logger = get_logger(__name__)


def _strict_contribution_enabled() -> bool:
    return bool(getattr(settings, "kernel_agent_runtime_v3_strict", False))


def _strict_evidence_enabled() -> bool:
    return bool(getattr(settings, "kernel_unified_evidence_strict", False))


class AgentRuntimeExecutor:
    """Enterprise agent execution facade (tier-1 CapabilityRegistry agents)."""

    async def execute_task(
        self,
        agent: BaseAgent,
        task: TaskMessage,
        *,
        goal_id: str = "",
        goal_description: str = "",
        capability_type: str = "",
        trace_id: str = "",
        evidence_bus: Any | None = None,
    ) -> AgentContribution:
        started = time.perf_counter()
        from agents.evidence_helpers import attach_evidence_objects

        result = await agent.execute(task)
        attach_evidence_objects(result)
        latency_ms = int((time.perf_counter() - started) * 1000)

        contribution = contribution_from_agent_result(
            result,
            goal_id=goal_id,
            goal_description=goal_description,
            capability_type=capability_type,
            trace_id=trace_id,
            latency_ms=latency_ms,
        )
        runtime_contrib = runtime_contribution_from_agent_result(
            result,
            goal_id=goal_id,
            goal_description=goal_description,
            capability_type=capability_type,
            trace_id=trace_id,
            latency_ms=latency_ms,
            session_id=str(getattr(task, "session_id", "") or ""),
        )
        contribution.trace = {
            **(contribution.trace or {}),
            **runtime_contrib.to_metadata_dict(),
        }

        if evidence_bus is not None and contribution.unified_evidence:
            try:
                await publish_unified_to_bus(
                    evidence_bus,
                    contribution.unified_evidence,
                    goal_id=goal_id,
                    capability_type=contribution.capability_type,
                    trace_id=trace_id,
                )
            except Exception as exc:
                logger.warning("Unified evidence bus publish failed", error=str(exc))
                if _strict_evidence_enabled():
                    raise

        violations = self.validate_contribution(contribution)
        if violations and _strict_contribution_enabled():
            raise RuntimeError(f"agent_contribution_contract_violation:{violations}")

        if violations:
            logger.debug("Agent contribution soft violations", violations=violations)

        return contribution

    def validate_contribution(self, contribution: AgentContribution) -> list[str]:
        violations: list[str] = []
        manifest = get_manifest()
        ent = manifest.get(contribution.agent_type)
        if ent and ent.runtime == "tier2":
            violations.append("tier2_agent_in_tier1_executor")
        if contribution.status in ("success", "ok", "done") and not contribution.content and not contribution.unified_evidence:
            violations.append("empty_success_payload")
        if contribution.goal and contribution.goal.goal_id and not contribution.goal.evidence_ids and contribution.unified_evidence:
            violations.append("goal_evidence_id_drift")
        if _strict_evidence_enabled() and contribution.status in ("success", "ok", "done"):
            if not contribution.unified_evidence:
                violations.append("missing_unified_evidence")
        return violations

    def contribution_to_agent_result(self, contribution: AgentContribution) -> AgentResult:
        data = contribution.to_agent_result_dict()
        return AgentResult.model_validate(data)


agent_runtime_executor = AgentRuntimeExecutor()