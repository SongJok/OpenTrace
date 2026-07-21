"""自我模型：系统能力评估与边界描述。"""

from __future__ import annotations

from datetime import datetime

from agents.registry import AgentRegistry
from infra.config.settings import settings
from kernel.cognition.types import CapabilityAssessment, CapabilityLevel, SelfState, TaskDomain


class SelfModel:
    IDENTITY = {
        "name": "OpenTrace Cognitive Kernel",
        "version": "4.x",
        "role": "企业级认知编排与决策辅助系统",
        "persona": "专业、审慎、透明、可审计",
    }

    CORE_CAPABILITIES = {
        TaskDomain.DATA_QUERY: {
            "prerequisites": ["data_agent", "connected_datasource"],
            "constraints": ["只读查询", "需要预先同步 schema"],
        },
        TaskDomain.DOCUMENT_RETRIEVAL: {
            "prerequisites": ["rag_agent", "indexed_documents"],
            "constraints": ["仅限已上传文档"],
        },
        TaskDomain.WEB_SEARCH: {
            "prerequisites": ["web_agent"],
            "constraints": ["依赖第三方服务"],
        },
        TaskDomain.TOOL_EXECUTION: {
            "prerequisites": ["tool_agent", "registered_tools"],
            "constraints": ["受沙箱限制"],
        },
        TaskDomain.GENERAL_QA: {
            "prerequisites": ["model_gateway"],
            "constraints": ["受模型知识时效限制"],
        },
    }

    def __init__(self) -> None:
        self._state: SelfState | None = None
        self._agent_registry = AgentRegistry()

    def refresh_state(self) -> SelfState:
        enabled_agents: list[str] = []
        if bool(settings.kernel_agent_enabled):
            if bool(settings.kernel_agent_data_enabled):
                enabled_agents.append("data")
            if bool(settings.kernel_agent_web_enabled):
                enabled_agents.append("web")
            if bool(settings.kernel_agent_tool_enabled):
                enabled_agents.append("tool")
            if bool(settings.kernel_agent_rag_enabled):
                enabled_agents.append("rag")

        available_tools: list[str] = []
        try:
            available_tools = list(self._agent_registry.get_tool_names())
        except Exception:
            available_tools = []

        self._state = SelfState(
            timestamp=datetime.now(),
            enabled_agents=enabled_agents,
            available_tools=available_tools,
            connected_data_sources=[],
            model_routing={
                "query": str(getattr(settings, "query_model", "default")),
                "planning": str(getattr(settings, "planning_model", "default")),
            },
            degraded_mode=False,
            degraded_reason=None,
        )
        return self._state

    def introspect(self, query: str, intent: TaskDomain) -> CapabilityAssessment:
        state = self._state or self.refresh_state()
        cap = self.CORE_CAPABILITIES.get(intent)
        if not cap:
            return CapabilityAssessment(
                domain=intent,
                level=CapabilityLevel.UNAVAILABLE,
                confidence=0.0,
                required_agents=[],
                expected_latency_ms=0,
                reasoning="未知任务领域",
            )

        missing: list[str] = []
        for p in cap["prerequisites"]:
            if p == "data_agent" and "data" not in state.enabled_agents:
                missing.append("DataAgent 未启用")
            if p == "web_agent" and "web" not in state.enabled_agents:
                missing.append("WebAgent 未启用")
            if p == "rag_agent" and "rag" not in state.enabled_agents:
                missing.append("RagAgent 未启用")
            if p == "tool_agent" and "tool" not in state.enabled_agents:
                missing.append("ToolAgent 未启用")
            if p == "registered_tools" and not state.available_tools:
                missing.append("没有已注册工具")

        if missing:
            return CapabilityAssessment(
                domain=intent,
                level=CapabilityLevel.UNAVAILABLE,
                confidence=0.0,
                required_agents=list(cap["prerequisites"]),
                expected_latency_ms=0,
                constraints=list(cap["constraints"]),
                fallback_strategy="请调整请求范围或检查能力开关",
                reasoning=f"缺少前置条件: {', '.join(missing)}",
            )

        # Capability Intelligence: use profiler data for accurate latency and reliability
        expected_latency_ms = 1500
        confidence = 0.9
        try:
            from kernel.capability_intelligence import _capability_intelligence_enabled

            if _capability_intelligence_enabled():
                from kernel.capability_intelligence import capability_profiler
                from kernel.runtime.capability import capability_registry

                capability_profiler.build_profiles(capability_registry)
                domain_map = {
                    TaskDomain.DATA_QUERY: "data.query",
                    TaskDomain.DOCUMENT_RETRIEVAL: "rag.retrieve",
                    TaskDomain.WEB_SEARCH: "web.search",
                    TaskDomain.TOOL_EXECUTION: "tool.datetime",
                }
                cap_type = domain_map.get(intent)
                if cap_type:
                    profile = capability_profiler.get_profile(cap_type)
                    if profile:
                        expected_latency_ms = profile.expected_latency_ms
                        confidence = profile.reliability
        except Exception:
            pass

        return CapabilityAssessment(
            domain=intent,
            level=CapabilityLevel.FULL,
            confidence=confidence,
            required_agents=list(cap["prerequisites"]),
            expected_latency_ms=expected_latency_ms,
            constraints=list(cap["constraints"]),
            reasoning=f"任务 {intent.value} 前置条件满足",
        )

    def get_identity_prompt(self) -> str:
        state = self._state or self.refresh_state()
        capability_desc = "、".join(state.enabled_agents) if state.enabled_agents else "无"

        # Capability Intelligence: use rich capability descriptions
        try:
            from kernel.capability_intelligence import _capability_intelligence_enabled

            if _capability_intelligence_enabled():
                from kernel.capability_intelligence import capability_profiler, CapabilityAdapter
                from kernel.runtime.capability import capability_registry

                capability_profiler.build_profiles(capability_registry)
                profiles = capability_profiler.list_profiles()
                if profiles:
                    adapter = CapabilityAdapter()
                    capability_desc = adapter.format_for_self_model(profiles)
        except Exception:
            pass

        return (
            f"你是 {self.IDENTITY['name']} v{self.IDENTITY['version']}。\n"
            f"角色: {self.IDENTITY['role']}。\n"
            f"风格: {self.IDENTITY['persona']}。\n"
            f"可用能力: {capability_desc}。\n"
            "能力边界: 仅在可验证证据范围内回答，不执行未授权高风险操作。"
        )
