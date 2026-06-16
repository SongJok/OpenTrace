"""
统一能力注册表 — 将 agent、工具、技能和插件汇聚为
编排器可发现的单一目录。

取代此前分散的注册表：
  - agents/registry.py        → 委托至此
  - tools/registry/registry.py → 委托至此
  - kernel/tools/registry.py   → 已弃用
  - plugins/selector.py        → 注册至此
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from infra.observability.logger import get_logger

logger = get_logger(__name__)

CapabilityType = Literal["agent", "tool", "skill", "plugin"]


@dataclass
class Capability:
    """系统中任何可执行能力的统一描述符。"""

    name: str
    cap_type: CapabilityType
    description: str
    tags: list[str] = field(default_factory=list)
    executor: Callable | None = None
    agent_type: str | None = None
    tool_spec: Any = None  # 来自 tools/registry 的 ToolSpec
    resource_type: str = "cpu"
    avg_latency_ms: int = 100
    required_permissions: list[str] = field(default_factory=list)
    # 语义增强字段
    domains: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    pairs_with: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    latency_tier: str = "medium"  # low | medium | high
    cost_tier: str = "medium"     # low | medium | high


class CapabilityRegistry:
    """线程安全的统一能力注册表。

    编排器查询此单一注册表以发现可用的 agent、工具、技能和插件，
    用于构建执行计划。
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}
        # 延迟引用，避免模块级循环导入
        self._agent_instances: dict[str, Any] = {}

    # ── 注册 ────────────────────────────────────────────────────────────

    def register_agent(self, agent: Any) -> None:
        """注册一个 agent 实例。"""
        agent_type = agent.agent_type
        self._agent_instances[agent_type] = agent
        desc = getattr(agent, "__doc__", "") or f"{agent_type} agent"
        self._capabilities[agent_type] = Capability(
            name=agent_type,
            cap_type="agent",
            description=desc.strip().split("\n")[0] if desc else f"{agent_type} agent",
            agent_type=agent_type,
            executor=agent.execute,
            tags=[agent_type],
        )
        logger.debug("Capability registered", name=agent_type, cap_type="agent")

    def register_tool(self, spec: Any) -> None:
        """注册一个工具规格（来自 tools/registry 的 ToolSpec）。"""
        self._capabilities[spec.name] = Capability(
            name=spec.name,
            cap_type="tool",
            description=spec.description,
            tags=spec.tags or [],
            executor=spec.fn,
            tool_spec=spec,
        )
        logger.debug("Capability registered", name=spec.name, cap_type="tool")

    def register_skill(self, skill_def: dict) -> None:
        """从定义字典注册一个技能。"""
        name = skill_def["name"]
        self._capabilities[name] = Capability(
            name=name,
            cap_type="skill",
            description=skill_def.get("description", ""),
            tags=skill_def.get("tags", []),
        )
        logger.debug("Capability registered", name=name, cap_type="skill")

    def register_plugin(self, name: str, plugin_cls: type) -> None:
        """注册一个插件类。"""
        doc = getattr(plugin_cls, "__doc__", "") or ""
        self._capabilities[name] = Capability(
            name=name,
            cap_type="plugin",
            description=doc.strip().split("\n")[0],
            tags=[name],
        )
        logger.debug("Capability registered", name=name, cap_type="plugin")

    # ── 查找 ──────────────────────────────────────────────────────────────

    def get_agent(self, agent_type: str) -> Any:
        key = (agent_type or "").lower()
        if key not in self._agent_instances:
            raise KeyError(f"agent not found: {agent_type}")
        return self._agent_instances[key]

    def has_agent(self, agent_type: str) -> bool:
        return (agent_type or "").lower() in self._agent_instances

    def get_tool(self, name: str) -> Any | None:
        cap = self._capabilities.get(name)
        if cap and cap.tool_spec:
            return cap.tool_spec
        return None

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def _web_intelligence_enabled(self) -> bool:
        try:
            from infra.config.settings import settings

            if not bool(getattr(settings, "kernel_web_intelligence_preferred", True)):
                return False
        except Exception as exc:
            logger.warning("web_intelligence_setting_read_skipped", error=str(exc))
        return self.has_agent("web_intelligence")

    def resolve_capability_type(self, name: str) -> str:
        """Map registry name / agent_type to canonical capability_type (manifest SSOT)."""
        try:
            from kernel.agent_runtime.manifest import get_manifest

            cap, _reg = get_manifest().resolve_capability_alias(name)
            if cap:
                return cap
        except Exception as exc:
            logger.warning("manifest_capability_resolve_skipped", name=name, error=str(exc))
        key = (name or "").lower()
        cap = self._capabilities.get(key)
        if cap and cap.agent_type:
            return self.resolve_capability_type(cap.agent_type)
        aliases = {
            "data": "data_query",
            "rag": "document_retrieval",
            "web": "web_search",
            "web_intelligence": "web_search",
            "web_intel": "web_search",
        }
        return aliases.get(key, key)

    def resolve_execution_agent(self, agent_type: str) -> str:
        """Map planner capability_type / alias to registered agent instance name."""
        try:
            from kernel.agent_runtime.manifest import get_manifest

            _cap, reg = get_manifest().resolve_capability_alias(agent_type)
            if reg and self.has_agent(reg):
                return reg
            if reg == "web_intelligence" and not self.has_agent(reg) and self.has_agent("web"):
                return "web"
        except Exception as exc:
            logger.warning("manifest_execution_agent_resolve_skipped", agent_type=agent_type, error=str(exc))
        key = (agent_type or "").lower()
        if self.has_agent(key):
            return key
        fallbacks = {
            "data_query": "data",
            "document_retrieval": "rag",
            "web_search": "web_intelligence" if self._web_intelligence_enabled() else "web",
            "vision_analysis": "vision",
            "skill_execution": "skills",
            "policy_rules": "rules",
            "data": "data",
            "rag": "rag",
            "vision": "vision",
            "skills": "skills",
            "rules": "rules",
        }
        alt = fallbacks.get(key)
        if alt and self.has_agent(alt):
            return alt
        return key

    def validate_for_execution(
        self, capability_type: str, *, environment: str = "default"
    ) -> list[str]:
        from kernel.capability_runtime.contract import validate_capability_execution
        from kernel.protocol.runtime_contract import CapabilityRef

        ctype = self.resolve_capability_type(capability_type)
        return validate_capability_execution(
            CapabilityRef(capability_type=ctype), environment=environment
        )

    def runtime_metadata(self, capability_type: str) -> dict[str, Any]:
        from kernel.capability_runtime.metadata import enrich_capability_ref
        from kernel.protocol.runtime_contract import CapabilityRef

        ctype = self.resolve_capability_type(capability_type)
        ref = enrich_capability_ref(CapabilityRef(capability_type=ctype))
        return dict((ref.params or {}).get("_runtime_meta") or {})

    def list_agents(self) -> list[str]:
        return list(self._agent_instances.keys())

    def list_all(self) -> dict[str, list[str]]:
        """按类型分组能力。"""
        grouped: dict[str, list[str]] = {}
        for cap in self._capabilities.values():
            grouped.setdefault(cap.cap_type, []).append(cap.name)
        return grouped

    # ── 意图匹配 ─────────────────────────────────────────────────────────

    def match(
        self,
        query: str,
        cap_type: CapabilityType | None = None,
        top_k: int = 5,
    ) -> list[Capability]:
        """基于 BM25 思路的能力匹配。

        按 cap_type 过滤（若给定），按名称 + 描述 + 标签的词项重叠评分，
        返回 top_k 结果。
        """
        tokens = set(_tokenize(query))
        if not tokens:
            return []

        candidates = self._capabilities.values()
        if cap_type:
            candidates = [c for c in candidates if c.cap_type == cap_type]

        scored: list[tuple[Capability, float]] = []
        for cap in candidates:
            doc_text = f"{cap.name} {cap.description} {' '.join(cap.tags)}"
            doc_tokens = _tokenize(doc_text)
            if not doc_tokens:
                continue

            tf = sum(doc_tokens.count(t) for t in tokens)
            name_bonus = 3.0 if any(t in cap.name.lower() for t in tokens) else 0.0
            tag_bonus = sum(
                1.5 for tag in cap.tags if any(t in tag.lower() for t in tokens)
            )
            raw_score = tf + name_bonus + tag_bonus

            if raw_score > 0:
                scored.append((cap, raw_score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[:top_k]]


def _tokenize(text: str) -> list[str]:
    import re

    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9]+|[一-鿿]+", lowered)
    out: list[str] = []
    for tok in tokens:
        out.append(tok)
        if re.fullmatch(r"[一-鿿]+", tok) and len(tok) > 1:
            out.extend(list(tok))
    return out


# 模块级单例
capability_registry = CapabilityRegistry()
