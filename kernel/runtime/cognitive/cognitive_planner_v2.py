"""
CognitivePlannerV2 — 生成 CognitivePlan（思考什么）而非 ExecutionPlan（如何执行）。

一次 LLM 调用深度推理查询，输出结构化认知模型：
目标层级、不确定性评估、推理链、信息缺口、约束条件和风险分析。

StrategyBuilder 随后消费此 CognitivePlan 以生成 ExecutionPlan。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kernel.runtime.context import RuntimeContext
    from kernel.runtime.objects import UnderstandingResult

from infra.config.settings import settings
from infra.observability.logger import get_logger

from .cognitive_graph import (
    CognitiveConstraint,
    CognitiveGraph,
    CognitivePlan,
    GoalHierarchy,
    GoalNode,
    GoalType,
    InformationGap,
    ReasoningChain,
    ReasoningStep,
    RiskAnalysis,
    UncertaintyModel,
)

logger = get_logger(__name__)

# 过于简单、不需要完整认知分解的查询
_SIMPLE_PATTERNS = [
    r"^(你好|hi|hello|嘿|嗨)[\s!！。.,，]*$",
    r"^(谢谢|thank|thanks|3Q|thx)[\s!！。.,，]*$",
    r"^(再见|bye|拜拜|88)[\s!！。.,，]*$",
    r"^(帮助|help|帮帮我)[\s!！。.,，]*$",
    r"^(是的|对|没错|嗯|好的|ok|OK)[\s!！。.,，]*$",
    r"^(继续|接着|然后)[\s!！。.,，]*$",
]


class CognitivePlannerV2:
    """从 UnderstandingResult + RuntimeContext 生成完整的 CognitivePlan。

    这是系统的"思维大脑" — 它在任何执行之前先推理需要弄清楚什么。
    一次 LLM 调用，一个决策，此层不做增量重规划。
    """

    def __init__(self, capability_registry: Any = None) -> None:
        self._capability_registry = capability_registry

    # ── 公共 API ──────────────────────────────────────────────────────────

    async def plan(
        self,
        query: str,
        ctx: RuntimeContext,
        understanding: UnderstandingResult | None = None,
    ) -> CognitivePlan:
        """从查询 + 上下文 + 理解结果生成 CognitivePlan。

        强制模式：返回只有单一目标的平凡 CognitivePlan。
        简单查询：启发式 CognitivePlan（不调用 LLM）。
        普通查询：一次 LLM 调用 → 完整 CognitiveGraph。
        """
        # ── 强制模式快捷路径 ──
        if ctx.force_mode:
            return self._trivial_plan(query, ctx)

        # ── 极简查询 ──
        for pattern in _SIMPLE_PATTERNS:
            if re.match(pattern, query.strip()):
                return self._trivial_plan(query, ctx)

        # ── 完整认知规划 ──
        return await self._plan_via_llm(query, ctx, understanding)

    # ── LLM 驱动的认知规划 ───────────────────────────────────────────────

    async def _plan_via_llm(
        self,
        query: str,
        ctx: RuntimeContext,
        understanding: UnderstandingResult | None,
    ) -> CognitivePlan:
        system_prompt = self._build_system_prompt(ctx, understanding)
        user_prompt = self._build_user_prompt(query, ctx, understanding)

        try:
            from model.model_gateway.gateway import LLMMessage, LLMRole, get_model_gateway

            gw = get_model_gateway()
            resp = await gw.complete(
                [
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=user_prompt),
                ],
                role=LLMRole.QUERY,
                temperature=0.0,
                max_tokens=2000,
            )
            text = (resp.content or "").strip()
        except Exception as exc:
            logger.error("CognitivePlannerV2 LLM call failed", error=str(exc))
            return self._trivial_plan(query, ctx)

        return self._parse_cognitive_plan(text, query, ctx, understanding)

    # ── 提示词构建器 ─────────────────────────────────────────────────────

    def _build_system_prompt(
        self, ctx: RuntimeContext, understanding: UnderstandingResult | None
    ) -> str:
        understanding_block = ""
        if understanding and understanding.explicit_goal:
            understanding_block = f"""
## 来自 UnderstandingEngine 的任务理解
- 明确目标: {understanding.explicit_goal}
- 隐含需求: {understanding.hidden_goal or '无'}
- 识别实体: {json.dumps(understanding.entities, ensure_ascii=False) if understanding.entities else '无'}
- 约束条件: {', '.join(understanding.constraints) if understanding.constraints else '无'}
- 歧义点: {understanding.ambiguity or '无'}
- 风险级别: {understanding.risk_level}
- 预期输出类型: {understanding.expected_output_type}
- 推荐能力: {', '.join(understanding.required_capabilities) if understanding.required_capabilities else '待定'}
"""

        capability_block = self._build_capability_block()
        intent_block = self._build_intent_constraint_block(ctx)

        return f"""你是 OpenTrace Cognitive Planner V2 — 系统的中央认知规划大脑。

## 你的职责
你不是任务编排器（那是 StrategyBuilder 的工作）。你的职责是**深度理解**用户请求，
输出结构化的认知模型：目标层级、不确定性分析、推理链、信息缺口、约束条件、风险评估。

## 核心原则
1. **Think before execute**: 先思考清楚 WHAT，不要跳到 HOW
2. **Goal-oriented**: 拆解认知目标，不是拆解执行任务
3. **Uncertainty-first**: 明确列出不确定的地方、需要验证的假设
4. **Gap-driven**: 信息缺口驱动后续证据收集策略
5. **Constraint-aware**: 领域约束、用户约束、逻辑约束必须明确

{intent_block}
{capability_block}
## 输出结构说明
{understanding_block}

### goal_hierarchy（目标层级树）
从用户主要目标出发，层层分解为子目标。目标是认知单元（"弄清楚X"），不是执行单元（"调Y API"）。

### uncertainty_model（不确定性模型）
- unknown_entities: 还不知道的实体
- unknown_facts: 还需要验证的事实
- ambiguous_terms: 可能有歧义的术语
- conflicting_hypotheses: 矛盾假设及其两个对立面
- confidence_threshold: 能接受的最低置信度

### information_gaps（信息缺口）
每个缺口描述一段缺失的信息，以及建议从哪里获取（rag/web/data/memory）。
**重要约束**：如果意图约束中仅允许某类能力，则 suggested_source 必须符合允许列表。
如果仅允许 model.answer（直接 LLM 推理），则 information_gaps 必须为空数组 []。
禁止使用被禁能力的 suggested_source。
映射关系：rag → rag.retrieve, web → web.search, data → data.query, memory → memory.retrieve。

### reasoning_chains（推理链）
从问题到答案的逻辑推理步骤。每条链服务于一个目标。

### constraints（认知约束）
领域规则、用户要求、输出约束等。

### risk_analysis（风险分析）
识别执行风险、建议缓解策略。

## 输出格式（纯 JSON，无 markdown 包裹）
{{
  "domain": "finance|sales|hr|engineering|general|...",
  "complexity_score": 0.0-1.0,
  "goal_hierarchy": {{
    "root_goal": {{
      "description": "用户主要目标",
      "goal_type": "primary",
      "priority": "high",
      "completion_criteria": "如何判断这个目标已完成"
    }},
    "sub_goals": [
      {{
        "description": "子目标描述",
        "goal_type": "decomposition|verification|exploration|comparison",
        "parent_index": -1,
        "priority": "high|normal|low",
        "depends_on_indices": [],
        "completion_criteria": "完成标准"
      }}
    ]
  }},
  "uncertainty_model": {{
    "unknown_entities": ["实体名"],
    "unknown_facts": ["不确定的事实"],
    "ambiguous_terms": ["有歧义的术语"],
    "conflicting_hypotheses": [{{"hypothesis_a": "假设A", "hypothesis_b": "假设B"}}],
    "confidence_threshold": 0.6
  }},
  "information_gaps": [
    {{
      "description": "缺失什么信息",
      "gap_type": "fact|entity|relation|constraint|verification",
      "query_template": "如何请求这个信息",
      "required_confidence": 0.6,
      "suggested_source": "rag|web|data|memory",
      "priority": "high|normal|low"
    }}
  ],
  "reasoning_chains": [
    {{
      "serves_goal_index": 0,
      "chain_type": "linear|branching|comparative",
      "expected_output_type": "text|table|chart|code",
      "steps": [
        {{
          "description": "推理步骤",
          "step_type": "inference|lookup|compute|compare|verify",
          "outputs": "步骤产出",
          "confidence": 0.8
        }}
      ]
    }}
  ],
  "constraints": [
    {{
      "description": "约束描述",
      "constraint_type": "domain|user|temporal|logical|output",
      "severity": "hard|soft"
    }}
  ],
  "risk_analysis": {{
    "risk_level": "low|medium|high|critical",
    "risks": [{{"description": "风险", "likelihood": "low|medium|high", "impact": "low|medium|high"}}],
    "mitigation_strategies": ["缓解策略"],
    "requires_human_approval": false
  }},
  "memory_dependencies": ["需要依赖的历史记忆描述"],
  "evidence_requirements": [{{"type": "table|text|chart", "description": "需要的证据"}}],
  "expected_artifacts": [{{"type": "answer|report|chart|code", "description": "预期产出物"}}]
}}"""

    def _build_capability_block(self) -> str:
        """构建 LLM 系统提示词中的能力目录块。"""
        try:
            from kernel.capability_intelligence import (
                _capability_intelligence_enabled,
                capability_profiler,
                CapabilityAdapter,
            )

            if not _capability_intelligence_enabled():
                return ""
            if self._capability_registry is None:
                return ""

            capability_profiler.build_profiles(self._capability_registry)
            profiles = capability_profiler.list_profiles()
            if not profiles:
                return ""

            adapter = CapabilityAdapter()
            catalog = adapter.format_for_cognitive_planner(profiles)
            return f"\n## 可用能力（Capability Catalog）\n{catalog}\n"
        except Exception:
            return ""

    def _build_intent_constraint_block(self, ctx: RuntimeContext) -> str:
        """将 Intent Lock 的允许/禁止能力约束注入 LLM prompt。"""
        allowed = getattr(ctx, "allowed_capabilities", []) or []
        disallowed = getattr(ctx, "disallowed_capabilities", []) or []
        task_type = getattr(ctx, "task_type", "general_qa") or "general_qa"

        if not allowed and not disallowed:
            return ""

        parts: list[str] = ["## 意图约束 (Intent Lock)"]
        parts.append(f"当前任务类型: {task_type}")

        if allowed:
            parts.append(f"仅允许使用以下能力: {', '.join(allowed)}")
            if "model.answer" in allowed and len(allowed) == 1:
                parts.append(
                    "**关键**: 'model.answer' 表示你必须直接用 LLM 推理回答，"
                    "不允许使用任何外部检索工具。"
                    "将所有 information_gaps 设为空数组 []，"
                    "所有 suggested_source 必须为空字符串。"
                )

        if disallowed:
            parts.append(f"严格禁止使用以下能力: {', '.join(disallowed)}")
            parts.append(
                "suggested_source 绝对不能设为上述禁止值。"
                "映射: rag→rag.retrieve, web→web.search, "
                "data→data.query, memory→memory.retrieve"
            )

        return "\n".join(parts) + "\n"

    def _build_user_prompt(
        self,
        query: str,
        ctx: RuntimeContext,
        understanding: UnderstandingResult | None,
    ) -> str:
        parts: list[str] = [f"## 用户提问\n{query}"]

        if ctx.conversation_history:
            recent = ctx.conversation_history[-4:]
            history_text = "\n".join(
                f"[{h.get('role', '?')}]: {str(h.get('content', ''))[:200]}"
                for h in recent
            )
            parts.append(f"## 最近对话\n{history_text}")

        if ctx.memory_context:
            parts.append(f"## 相关记忆\n{ctx.memory_context[:1000]}")

        if ctx.preference_context_block:
            parts.append(f"## 用户偏好\n{ctx.preference_context_block[:800]}")

        ds = ctx.data_source_context
        if ds.get("data_source_id"):
            parts.append(
                f"## 数据源\n绑定: {ds.get('data_source_name', '')} "
                f"(type={ds.get('source_type', '')}, db={ds.get('database', '')})"
            )

        return "\n\n".join(parts)

    # ── JSON 解析器 ──────────────────────────────────────────────────────────

    def _parse_cognitive_plan(
        self,
        text: str,
        query: str,
        ctx: RuntimeContext,
        understanding: UnderstandingResult | None,
    ) -> CognitivePlan:
        text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        text = re.sub(r"\n?\s*```\s*$", "", text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("CognitivePlannerV2 JSON parse failed", raw=text[:200])
            return self._trivial_plan(query, ctx)

        if not isinstance(data, dict):
            return self._trivial_plan(query, ctx)

        # ── 解析目标层级 ──
        gh_data = data.get("goal_hierarchy", {})
        root_data = gh_data.get("root_goal", {})
        root_goal = GoalNode(
            description=str(root_data.get("description", query)),
            goal_type=GoalType.PRIMARY,
            priority=str(root_data.get("priority", "high")),
            completion_criteria=str(root_data.get("completion_criteria", "")),
        )
        hierarchy = GoalHierarchy(root_goal=root_goal)
        hierarchy.add_goal(root_goal)

        sub_goals_data = gh_data.get("sub_goals", []) or []
        goals_list: list[GoalNode] = [root_goal]
        for i, sg in enumerate(sub_goals_data):
            if not isinstance(sg, dict):
                continue
            goal_type_str = sg.get("goal_type", "decomposition")
            try:
                goal_type = GoalType(goal_type_str)
            except ValueError:
                goal_type = GoalType.DECOMPOSITION

            parent_idx = int(sg.get("parent_index", 0))
            parent_id = root_goal.goal_id
            if 0 <= parent_idx < len(goals_list):
                parent_id = goals_list[parent_idx].goal_id

            goal = GoalNode(
                description=str(sg.get("description", "")),
                goal_type=goal_type,
                parent_id=parent_id,
                priority=str(sg.get("priority", "normal")),
                depends_on=[],
                completion_criteria=str(sg.get("completion_criteria", "")),
            )
            goals_list.append(goal)
            hierarchy.add_goal(goal)
            if parent_id in hierarchy.all_goals:
                hierarchy.all_goals[parent_id].children.append(goal.goal_id)

        # ── 解析 depends_on_indices → depends_on ──
        for i, sg in enumerate(sub_goals_data):
            if i + 1 >= len(goals_list):
                break
            goal = goals_list[i + 1]
            dep_indices = sg.get("depends_on_indices", []) or []
            for di in dep_indices:
                if 0 <= int(di) < len(goals_list):
                    goal.depends_on.append(goals_list[int(di)].goal_id)

        # ── 解析不确定性模型 ──
        um_data = data.get("uncertainty_model", {})
        uncertainty = UncertaintyModel(
            unknown_entities=list(um_data.get("unknown_entities", []) or []),
            unknown_facts=list(um_data.get("unknown_facts", []) or []),
            ambiguous_terms=list(um_data.get("ambiguous_terms", []) or []),
            conflicting_hypotheses=list(um_data.get("conflicting_hypotheses", []) or []),
            confidence_threshold=float(um_data.get("confidence_threshold", 0.6)),
        )

        # ── 解析信息缺口 ──
        gaps: list[InformationGap] = []
        for g in data.get("information_gaps", []) or []:
            if not isinstance(g, dict):
                continue
            gaps.append(InformationGap(
                description=str(g.get("description", "")),
                gap_type=str(g.get("gap_type", "fact")),
                query_template=str(g.get("query_template", "")),
                required_confidence=float(g.get("required_confidence", 0.6)),
                suggested_source=str(g.get("suggested_source", "")),
                priority=str(g.get("priority", "normal")),
            ))

        # ── 解析推理链 ──
        chains: list[ReasoningChain] = []
        for rc in data.get("reasoning_chains", []) or []:
            if not isinstance(rc, dict):
                continue
            goal_idx = int(rc.get("serves_goal_index", 0))
            goal_id = root_goal.goal_id
            if 0 <= goal_idx < len(goals_list):
                goal_id = goals_list[goal_idx].goal_id

            steps: list[ReasoningStep] = []
            for s in rc.get("steps", []) or []:
                if not isinstance(s, dict):
                    continue
                steps.append(ReasoningStep(
                    description=str(s.get("description", "")),
                    step_type=str(s.get("step_type", "inference")),
                    outputs=str(s.get("outputs", "")),
                    confidence=float(s.get("confidence", 0.8)),
                ))
            chains.append(ReasoningChain(
                goal_id=goal_id,
                steps=steps,
                chain_type=str(rc.get("chain_type", "linear")),
                expected_output_type=str(rc.get("expected_output_type", "text")),
            ))

        # ── 解析约束条件 ──
        constraints: list[CognitiveConstraint] = []
        for c in data.get("constraints", []) or []:
            if not isinstance(c, dict):
                continue
            constraints.append(CognitiveConstraint(
                description=str(c.get("description", "")),
                constraint_type=str(c.get("constraint_type", "domain")),
                severity=str(c.get("severity", "hard")),
            ))

        # ── 解析风险分析 ──
        ra_data = data.get("risk_analysis", {})
        risk_analysis = RiskAnalysis(
            risk_level=str(ra_data.get("risk_level", "low")),
            risks=list(ra_data.get("risks", []) or []),
            mitigation_strategies=list(ra_data.get("mitigation_strategies", []) or []),
            fallback_plan=str(ra_data.get("fallback_plan", "")),
            requires_human_approval=bool(ra_data.get("requires_human_approval", False)),
        )

        # ── 构建 CognitiveGraph ──
        cog_graph = CognitiveGraph(
            original_query=query,
            rewritten_query=query,
            goal_hierarchy=hierarchy,
            uncertainty_model=uncertainty,
            information_gaps=gaps,
            reasoning_chains=chains,
            constraints=constraints,
            risk_analysis=risk_analysis,
            domain=str(data.get("domain", understanding.domain if understanding else "general")),
            complexity_score=float(data.get("complexity_score", 0.5)),
            expected_turn_count=int(data.get("expected_turn_count", 1)),
        )

        # ── 构建 CognitivePlan ──
        plan = CognitivePlan(
            cognitive_graph=cog_graph,
            memory_dependencies=list(data.get("memory_dependencies", []) or []),
            evidence_requirements=list(data.get("evidence_requirements", []) or []),
            expected_artifacts=list(data.get("expected_artifacts", []) or []),
            execution_hints=data.get("execution_hints", {}) or {},
        )

        logger.info(
            "CognitivePlannerV2 plan generated",
            goals=len(hierarchy.all_goals),
            gaps=len(gaps),
            chains=len(chains),
            risk=risk_analysis.risk_level,
        )

        return plan

    # ── 平凡/回退计划 ──────────────────────────────────────────────────────

    def _trivial_plan(
        self, query: str, ctx: RuntimeContext
    ) -> CognitivePlan:
        root = GoalNode(
            description=query,
            goal_type=GoalType.PRIMARY,
            priority="high",
            completion_criteria="简短直接回复用户",
        )
        hierarchy = GoalHierarchy(root_goal=root)
        hierarchy.add_goal(root)

        cog_graph = CognitiveGraph(
            original_query=query,
            rewritten_query=query,
            goal_hierarchy=hierarchy,
            uncertainty_model=UncertaintyModel(),
            domain="general",
            complexity_score=0.1,
        )

        return CognitivePlan(cognitive_graph=cog_graph)
