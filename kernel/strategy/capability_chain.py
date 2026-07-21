"""能力 OS 链：Capability → Strategy → ExecutionPolicy → 工具绑定（契约）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kernel.protocol.runtime_contract import CapabilityRef, ExecutionPolicy

@dataclass
class CapabilityChainLink:
    capability: CapabilityRef
    strategy: str = "direct"
    execution_policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    tool_names: list[str] = field(default_factory=list)
    environment: str = "default"

def resolve_capability_chain(
    capability_type: str,
    *,
    force_mode: str = "",
    web_enabled: bool = False,
) -> CapabilityChainLink:
    """Map capability type to strategy + policy + tool hints (no execution)."""
    cap = CapabilityRef(capability_type=capability_type, strategy_hint=force_mode or "auto")
    policy = ExecutionPolicy(
        capability_executor_mode=True,
        sandbox_required=capability_type in ("python.execute",),
        timeout_sec=30,
    )
    tool_map: dict[str, list[str]] = {
        "rag.retrieve": ["rag"],
        "web.search": ["web_search"],
        "data.query": ["data"],
        "tool.datetime": ["get_current_time", "datetime"],
        "tool.weather": ["get_weather"],
        "model.answer": [],
    }
    strategy = "force" if force_mode else "capability_match"
    if capability_type == "web.search" and not web_enabled:
        strategy = "deny_web"
    return CapabilityChainLink(
        capability=cap,
        strategy=strategy,
        execution_policy=policy,
        tool_names=tool_map.get(capability_type, []),
    )