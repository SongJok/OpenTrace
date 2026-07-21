"""CapabilityAdapter — 将能力画像格式化为 LLM 提示。

连接结构化 CapabilityProfile 与规划器消费的自然语言提示块；
各 formatter 面向不同消费者（CognitivePlannerV2、UnderstandingEngine 等）。
"""

from __future__ import annotations

from kernel.capability_intelligence.profile import CapabilityProfile
from kernel.capability_intelligence.profiler import _bigram_score_cjk, _is_cjk_text


class CapabilityAdapter:
    """将能力画像格式化为高效的 LLM 提示块。"""

    @staticmethod
    def format_for_cognitive_planner(profiles: list[CapabilityProfile]) -> str:
        """为 CognitivePlannerV2 系统提示生成紧凑的能力目录。

        每条目约 3-5 行、50-80 token。包含擅长领域、局限、可靠性与预期延迟，
        使 LLM 能做出明智的能力选择决策。
        """
        if not profiles:
            return ""

        lines: list[str] = []
        for p in profiles:
            strengths = "、".join(p.strengths[:3]) if p.strengths else "通用处理"
            weaknesses = "、".join(p.weaknesses[:2]) if p.weaknesses else "无特殊限制"
            latency_str = f"{p.expected_latency_ms}ms" if p.expected_latency_ms else "unknown"
            outputs = "、".join(p.output_types[:3]) if p.output_types else "text"

            block = (
                f"- **{p.capability_type}**: {p.description}\n"
                f"  擅长: {strengths}\n"
                f"  局限: {weaknesses}\n"
                f"  可靠性: {p.reliability:.2f} | 延迟: ~{latency_str} | 输出: {outputs}"
            )
            lines.append(block)

        return "\n".join(lines)

    @staticmethod
    def format_for_understanding_engine(profiles: list[CapabilityProfile]) -> str:
        """为 UnderstandingEngine 提示生成简单的名称+描述列表。

        替代 understanding_engine.py 第 141-152 行的 11 条硬编码列表。
        """
        if not profiles:
            return ""

        return "\n".join(
            f"- {p.capability_type}: {p.description}" for p in profiles
        )

    @staticmethod
    def format_for_self_model(profiles: list[CapabilityProfile]) -> str:
        """为 SelfModel.get_identity_prompt() 生成能力描述。

        替代裸 agent 名称如 "data, web, tool, rag"。
        """
        if not profiles:
            return ""

        agent_groups: dict[str, list[str]] = {}
        for p in profiles:
            agent = p.agent_type or "other"
            if agent not in agent_groups:
                agent_groups[agent] = []
            agent_groups[agent].append(p.capability_type)

        parts: list[str] = []
        for agent, caps in sorted(agent_groups.items()):
            parts.append(f"{agent}（{'、'.join(caps)}）")
        return "、".join(parts)

    @staticmethod
    def find_best_capability(
        suggested_source: str,
        gap_description: str,
        profiles: list[CapabilityProfile],
    ) -> str | None:
        """为信息缺口找到最佳 capability_type。

        替代 StrategyBuilder._gap_to_capability() 中的 4 条硬编码字典。
        以 suggested_source 作为前缀提示，再回退到关键词匹配。
        """
        source = suggested_source.lower().strip()
        gap_lower = gap_description.lower()

        # 1. 前缀匹配："data" → data.*；"web" → web.*（优先 canonical web.search）
        if source:
            dot_prefix = source + "."
            prefix_matches = [
                p
                for p in profiles
                if p.capability_type.startswith(dot_prefix)
                or (p.agent_type == source and "." in p.capability_type)
            ]
            if source == "web":
                prefix_matches = list(
                    {
                        id(p): p
                        for p in prefix_matches
                        + [
                            p
                            for p in profiles
                            if p.agent_type in {"web_intelligence", "web"}
                            or p.capability_type in {"web_search", "web.search"}
                        ]
                    }.values()
                )
            if not prefix_matches and source:
                prefix_matches = [p for p in profiles if p.agent_type == source]
            if prefix_matches:
                if source == "web":
                    for p in prefix_matches:
                        if p.capability_type == "web.search":
                            return p.capability_type
                    try:
                        from kernel.agent_runtime.manifest import get_manifest

                        canonical_cap, _ = get_manifest().resolve_capability_alias("web")
                        for p in prefix_matches:
                            if p.capability_type == canonical_cap:
                                return p.capability_type
                        for p in prefix_matches:
                            if p.agent_type in {
                                get_manifest().resolve_capability_alias("web_intelligence")[1],
                                "web_intelligence",
                            }:
                                return p.capability_type
                    except Exception:
                        pass
                    for p in prefix_matches:
                        if p.capability_type in {"web_search", "web.search"}:
                            return p.capability_type
                canonical = f"{source}.search" if source == "web" else ""
                for p in prefix_matches:
                    if canonical and p.capability_type == canonical:
                        return p.capability_type
                prefix_matches.sort(key=lambda p: p.reliability, reverse=True)
                return prefix_matches[0].capability_type

        # 2. 关键词匹配：基于标签/擅长领域/描述（支持中文与英文）
        best_score = 0.0
        best_cap: str | None = None
        for p in profiles:
            search_text = " ".join(p.tags + p.strengths + [p.description]).lower()
            combined = f"{source} {gap_lower}"
            if _is_cjk_text(combined):
                score = _bigram_score_cjk(combined, search_text)
            else:
                words = set(combined.split())
                score = sum(1 for w in words if w in search_text) / max(len(words), 1)
            if score > best_score:
                best_score = score
                best_cap = p.capability_type

        # 要求最低分数以避免轻微重叠导致的误匹配
        if best_score < 0.18:
            return None
        return best_cap

    @staticmethod
    def format_knowledge_graph_for_prompt(kg) -> str:
        """为 LLM 提示格式化知识图谱关键关系。

        在能力目录后追加依赖/互补/替代摘要，使规划器理解能力间的交互关系。
        """
        if kg is None:
            return ""
        try:
            return kg.export_for_prompt()
        except Exception:
            return ""
