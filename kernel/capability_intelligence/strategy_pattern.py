"""StrategyPattern — planner-facing view over StrategyMemory."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from kernel.capability_intelligence.profile import StrategyRecord
from kernel.capability_intelligence.strategy_memory import StrategyMemory, strategy_memory


@dataclass
class StrategyPattern:
    intent_category: str = "general"
    agent_path: list[str] = field(default_factory=list)
    prompt_shape: str = "default"
    tool_pattern: str = ""
    success_rate: float = 0.0
    avg_latency_ms: int = 0
    sample_count: int = 0
    last_used: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_category": self.intent_category,
            "agent_path": list(self.agent_path),
            "prompt_shape": self.prompt_shape,
            "tool_pattern": self.tool_pattern,
            "success_rate": round(self.success_rate, 4),
            "avg_latency_ms": self.avg_latency_ms,
            "sample_count": self.sample_count,
            "last_used": self.last_used,
        }


def record_turn_pattern(
    *,
    intent_category: str,
    capabilities_used: list[str],
    strategy_type: str,
    success: bool,
    latency_ms: int,
    query_preview: str = "",
    prompt_shape: str = "default",
) -> StrategyPattern:
    """Persist a turn outcome as a strategy pattern (PII-safe preview only)."""
    preview = (query_preview or "")[:80]
    domain = (intent_category or "general")[:40]
    mem = strategy_memory
    mem.record(
        StrategyRecord(
            strategy_type=strategy_type or "direct",
            capabilities_used=list(capabilities_used or []),
            query_domain=domain,
            query_preview=preview,
            success=bool(success),
            turn_success=bool(success),
            latency_ms=int(latency_ms or 0),
            timestamp=time.time(),
        )
    )
    caps = list(capabilities_used or [])
    rec = mem.recommend(caps, query_domain=domain)
    return StrategyPattern(
        intent_category=domain,
        agent_path=caps,
        prompt_shape=prompt_shape,
        tool_pattern=strategy_type or "direct",
        success_rate=float(rec.confidence or 0.0),
        avg_latency_ms=int(latency_ms or 0),
        sample_count=1,
        last_used=time.time(),
    )


def top_k_patterns_for_planner(
    intent_category: str,
    capabilities: list[str] | None = None,
    k: int = 3,
) -> list[dict[str, Any]]:
    """Return Top-K strategy hints for StrategicPlanner / selector."""
    caps = list(capabilities or [])
    domain = (intent_category or "general")[:40]
    rec = strategy_memory.recommend(caps, query_domain=domain)
    patterns: list[dict[str, Any]] = [
        {
            "strategy_type": rec.strategy_type,
            "confidence": rec.confidence,
            "reasoning": rec.reasoning,
            "agent_path": caps,
            "intent_category": domain,
        }
    ]
    for alt_type, alt_score in (rec.alternatives or [])[: max(0, k - 1)]:
        patterns.append(
            {
                "strategy_type": alt_type,
                "confidence": alt_score,
                "reasoning": "alternative_from_strategy_memory",
                "agent_path": caps,
                "intent_category": domain,
            }
        )
    return patterns[:k]


def planner_enabled() -> bool:
    from infra.config.settings import settings

    if bool(getattr(settings, "kernel_strategy_memory_planner_enabled", True)):
        return True
    return bool(getattr(settings, "kernel_agent_learning_auto_apply", False))