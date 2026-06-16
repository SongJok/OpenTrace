"""
UnifiedOrchestrator — One LLM call replaces 6+ scattered calls.

Previous pipeline (to be eliminated):
  DST → ReferenceResolver → Multi-question detection → Correction path →
  PlanAgent.generate_plan() → Hard-guard auto-injection

New pipeline:
  RuntimeContext (full context) → ONE LLM call (QUERY role) → TaskPlan

The orchestration model receives:
  - User query (resolved with conversation history)
  - Available agents from CapabilityRegistry
  - Conversation history (last N turns)
  - Memory context (from EvolutionMemoryRouter)
  - User preferences / profile
  - Data source context (schema summary)
  - Attachment contexts
  - Conversation state (active topic, intent, last plan)

And outputs a complete TaskPlan: all subtasks with agent_type, query, params,
depends_on, priority — decided once, no fallback, no hard-guard, no replan.

force_mode shortcuts: 10 predefined modes that bypass LLM entirely.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kernel.plan_agent import SubTask, TaskPlan
    from kernel.runtime.context import RuntimeContext

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)

# ── Force mode → agent_type mapping ───────────────────────────────────────
FORCE_MODE_AGENT_MAP: dict[str, str] = {
    "rag": "rag",
    "data_query": "data",
    "data_analysis": "data",
    "anomaly_tracking": "skills",
    "product": "rule_engine",
    "rule_engine": "rule_engine",
    "tool": "tool",
    "skills": "skills",
    "web": "web",
    "vision": "vision",
}


class UnifiedOrchestrator:
    """One-shot planner — replaces PlanAgent + DST + ReferenceResolver + hard-guard.

    Input:  query + RuntimeContext (complete)
    Output: TaskPlan (all subtasks, one decision)
    """

    def __init__(self, capability_registry: Any = None) -> None:
        self._capability_registry = capability_registry

    # ── Public API ────────────────────────────────────────────────────────

    async def plan(self, query: str, ctx: RuntimeContext) -> TaskPlan:
        """Produce a complete TaskPlan in one pass.

        force_mode: skip LLM, map directly.
        Otherwise: one LLM call with full context.
        """
        # ═══ force_mode shortcut ═══
        if ctx.force_mode:
            return self._plan_from_force_mode(query, ctx)

        # ═══ One LLM call = full plan ═══
        return await self._plan_via_llm(query, ctx)

    # ── Force mode (shortcut, no LLM) ─────────────────────────────────────

    def _plan_from_force_mode(self, query: str, ctx: Any) -> Any:
        from kernel.plan_agent import SubTask, TaskPlan
        agent_type = FORCE_MODE_AGENT_MAP.get(ctx.force_mode or "", "rag")

        params: dict[str, Any] = {
            "session_id": ctx.session_id,
            "user_id": ctx.user_id,
        }

        if agent_type == "skills":
            params["enabled_skills"] = True

        elif agent_type == "rag":
            params.update({
                "top_k": 8,
                "sources": ["documents", "semantic_memory"],
                "min_score": 0.25,
            })

        elif agent_type == "data":
            ds = ctx.data_source_context
            params["data_source_id"] = ds.get("data_source_id", "")
            params["database"] = ds.get("database", "")
            params["schema"] = ds.get("schema", "")

        return TaskPlan(
            subtasks=[SubTask(agent_type=agent_type, query=query, params=params)],
            merge_strategy="direct",
            max_parallel=1,
            adaptive_profile=ctx.adaptive_profile,
        )

    # ── LLM-based one-shot planning ───────────────────────────────────────

    async def _plan_via_llm(self, query: str, ctx: Any) -> Any:
        """Single LLM call with complete RuntimeContext → TaskPlan JSON."""
        from kernel.plan_agent import SubTask, TaskPlan
        system_prompt = self._build_system_prompt(ctx)
        user_prompt = self._build_user_prompt(query, ctx)

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
                max_tokens=800,
            )
            text = (resp.content or "").strip()
        except Exception as exc:
            logger.error("UnifiedOrchestrator LLM call failed", error=str(exc))
            # Fall back to minimal plan
            return TaskPlan(
                subtasks=[SubTask(agent_type="rag", query=query, params={
                    "session_id": getattr(ctx, "session_id", ""),
                    "user_id": getattr(ctx, "user_id", ""),
                })],
                merge_strategy="direct",
                max_parallel=1,
                adaptive_profile=getattr(ctx, "adaptive_profile", {}),
            )

        return self._parse_plan(text, query, ctx, understanding=understanding)

    # ── Prompt builders ───────────────────────────────────────────────────

    def _build_system_prompt(self, ctx: RuntimeContext) -> str:
        agents_desc = self._format_available_agents()
        data_source_info = self._format_data_source(ctx)

        prompt = f"""你是 OpenTrade 认知编排器。根据用户的提问和完整上下文，一次性输出完整执行计划。

## 可用 Agent 能力
{agents_desc}

## 数据源信息
{data_source_info}

## 编排规则
1. 理解用户意图，消解指代，重写为完整查询
2. 将任务拆解为 1-5 个子任务，分配最合适的 Agent
3. 设置依赖关系（depends_on）：B 需要 A 的结果时，B.depends_on=[A.id]
4. 设置优先级：high（关键路径）、normal、low（可选增强）
5. 一次规划到位，不要试图"先试A不行再补B"，直接决定好需要哪些 Agent
6. 如果用户问了多个独立问题，拆为并行子任务
7. 有数据源绑定且问题涉及数据分析时，必须包含 data Agent
8. 涉及文档/知识/记忆检索时，加入 rag Agent
9. 需要实时信息/最新资讯时，加入 web Agent

## 输出格式（纯 JSON，无 markdown 包裹）
{{
  "rewritten_query": "消解指代后的完整查询",
  "intent_category": "data|rag|web|tool|general|mixed",
  "considerations": "执行注意事项（简短）",
  "subtasks": [
    {{
      "id": "task_1",
      "agent_type": "data|rag|web|tool|skills|rule_engine|vision",
      "query": "子任务查询文本",
      "params": {{"key": "value"}},
      "depends_on": [],
      "priority": "high|normal|low",
      "reason": "为什么需要这个子任务（简短）"
    }}
  ],
  "merge_strategy": "union|compare|prioritized"
}}
"""
        return prompt

    def _build_user_prompt(self, query: str, ctx: RuntimeContext) -> str:
        parts: list[str] = [f"## 用户提问\n{query}"]

        # Conversation history
        if ctx.conversation_history:
            recent = ctx.conversation_history[-6:]
            history_text = "\n".join(
                f"[{h.get('role', '?')}]: {str(h.get('content', ''))[:300]}"
                for h in recent
            )
            parts.append(f"## 最近对话历史\n{history_text}")

        # Memory context
        if ctx.memory_context:
            parts.append(f"## 相关记忆\n{ctx.memory_context[:1500]}")

        # User preferences
        if ctx.preference_context_block:
            parts.append(f"## 用户偏好\n{ctx.preference_context_block[:1000]}")

        # Data source context
        ds = ctx.data_source_context
        if ds.get("data_source_id"):
            ds_text = f"已绑定数据源: id={ds.get('data_source_id')}, name={ds.get('data_source_name')}, database={ds.get('database')}, source_type={ds.get('source_type')}"
            schema = ds.get("schema", "")
            if schema:
                ds_text += f"\nSchema摘要: {str(schema)[:2000]}"
            parts.append(f"## 数据源\n{ds_text}")

        # Attachment contexts
        if ctx.attachment_contexts:
            att_text = "\n".join(
                f"- {a.get('name', 'unknown')}: {str(a.get('content_summary', ''))[:500]}"
                for a in ctx.attachment_contexts
            )
            if att_text:
                parts.append(f"## 附件内容\n{att_text}")

        # Conversation state
        if ctx.conversation_state:
            cs = ctx.conversation_state
            if hasattr(cs, "to_db_dict"):
                cs = cs.to_db_dict()
            if isinstance(cs, dict) and (cs.get("active_topic") or cs.get("active_intent")):
                parts.append(
                    f"## 会话状态\nactive_topic={cs.get('active_topic')}, "
                    f"active_intent={cs.get('active_intent')}"
                )

        # Enabled/disabled skills
        if ctx.enabled_skills:
            parts.append(f"## 启用的技能\n{', '.join(ctx.enabled_skills)}")

        return "\n\n".join(parts)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _format_available_agents(self) -> str:
        try:
            if self._capability_registry:
                agents = self._capability_registry.list_agents()
                if agents:
                    lines = []
                    for name in agents:
                        try:
                            cap = self._capability_registry.get(name)
                            desc = cap.description if cap else ""
                        except Exception:
                            desc = ""
                        lines.append(f"- **{name}**: {desc}")
                    return "\n".join(lines)
        except Exception as exc:
            logger.debug("orchestrator_format_agents_skipped", error=str(exc))

        return """- **data**: 结构化数据查询（Text2SQL）
- **rag**: 内部文档 + 记忆检索
- **web**: 联网搜索实时信息
- **tool**: 工具调用（时间、天气、计算器等）
- **skills**: 专业技能调用
- **rule_engine**: 产品/规则查询
- **vision**: 图像/图表理解"""

    def _format_data_source(self, ctx: RuntimeContext) -> str:
        ds = ctx.data_source_context
        if not ds.get("data_source_id"):
            return "未绑定数据源。如果问题涉及数据查询，需要使用 rag 或 web 来回答。"
        return (
            f"已绑定数据源：{ds.get('data_source_name', 'unknown')} "
            f"(id={ds.get('data_source_id')}, database={ds.get('database', 'unknown')}, "
            f"source_type={ds.get('source_type', 'unknown')})"
        )

    def _parse_plan(self, text: str, query: str, ctx: Any) -> Any:
        """Parse the LLM JSON output into a TaskPlan."""
        from kernel.plan_agent import SubTask, TaskPlan
        # Strip markdown code fences if present
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.DOTALL)
        text = re.sub(r"\n?\s*```\s*$", "", text, flags=re.DOTALL)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("UnifiedOrchestrator JSON parse failed, using fallback", raw=text[:200])
            return self._fallback_plan(query, ctx)

        if not isinstance(data, dict) or "subtasks" not in data:
            return self._fallback_plan(query, ctx)

        subtasks_raw = data.get("subtasks", [])
        if not isinstance(subtasks_raw, list) or not subtasks_raw:
            return self._fallback_plan(query, ctx)

        subtasks: list[SubTask] = []
        for i, st in enumerate(subtasks_raw):
            if not isinstance(st, dict):
                continue
            agent_type = str(st.get("agent_type", "rag"))
            sub_query = str(st.get("query", query))
            params = dict(st.get("params", {}) or {})
            params.setdefault("session_id", ctx.session_id)
            params.setdefault("user_id", ctx.user_id)

            subtasks.append(SubTask(
                agent_type=agent_type,
                query=sub_query,
                params=params,
                depends_on=list(st.get("depends_on", []) or []),
                priority=str(st.get("priority", "normal")),
                sub_question_id=str(st.get("id", f"task_{i}")),
                display_order=i,
            ))

        plan = TaskPlan(
            subtasks=subtasks,
            merge_strategy=str(data.get("merge_strategy", "union")),
            max_parallel=ctx.adaptive_profile.get("max_parallel", 3),
            adaptive_profile=ctx.adaptive_profile,
            is_multi_question=len(subtasks) > 1,
        )

        logger.info(
            "UnifiedOrchestrator plan generated",
            subtask_count=len(subtasks),
            agents=[s.agent_type for s in subtasks],
            merge_strategy=plan.merge_strategy,
        )

        return plan

    def _fallback_plan(self, query: str, ctx: Any) -> Any:
        """Minimal fallback when LLM output can't be parsed."""
        from kernel.plan_agent import SubTask, TaskPlan
        return TaskPlan(
            subtasks=[SubTask(agent_type="rag", query=query, params={
                "session_id": ctx.session_id,
                "user_id": ctx.user_id,
            })],
            merge_strategy="direct",
            max_parallel=1,
            adaptive_profile=ctx.adaptive_profile,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CognitivePlanner — the central cognitive brain
# ═══════════════════════════════════════════════════════════════════════════════

class CognitivePlanner:
    """Central cognitive planner — the ONE brain that plans everything.

    Replaces PlanAgent + DST + ReferenceResolver + hard-guard logic.
    One LLM call produces a complete ExecutionPlan with capability assignments,
    risk assessment, completion criteria, and execution strategy.

    Input:  query + RuntimeContext + optional UnderstandingResult
    Output: ExecutionPlan (all subtasks with capability_type, one decision)
    """

    def __init__(self, capability_registry: Any = None) -> None:
        self._capability_registry = capability_registry

    async def plan(
        self,
        query: str,
        ctx: RuntimeContext,
        understanding: UnderstandingResult | None = None,
    ) -> ExecutionPlan:
        """Produce a complete ExecutionPlan in one pass.

        force_mode: skip LLM, map directly to capability.
        Otherwise: one LLM call with full context + understanding.
        """
        # ═══ force_mode shortcut ═══
        if ctx.force_mode:
            plan = self._plan_from_force_mode(query, ctx)
            return self._enrich_plan_from_understanding(plan, understanding)

        # ═══ One LLM call = full execution plan ═══
        plan = await self._plan_via_llm(query, ctx, understanding)
        return self._enrich_plan_from_understanding(plan, understanding)

    @staticmethod
    def _enrich_plan_from_understanding(
        plan: Any, understanding: UnderstandingResult | None
    ) -> Any:
        if understanding and not getattr(plan, "understanding_summary", ""):
            plan.understanding_summary = (
                understanding.explicit_goal
                or understanding.completion_criteria
                or ""
            )
        if understanding and not plan.required_capabilities:
            plan.required_capabilities = list(understanding.required_capabilities or [])
        return plan

    def _plan_from_force_mode(self, query: str, ctx: RuntimeContext) -> ExecutionPlan:
        from kernel.runtime.objects import ExecutionPlan, ExecutionTask

        agent_type = FORCE_MODE_AGENT_MAP.get(ctx.force_mode or "", "rag")
        capability_type = _agent_to_capability(agent_type)

        params: dict[str, Any] = {
            "session_id": ctx.session_id,
            "user_id": ctx.user_id,
        }

        if agent_type == "rag":
            params.update({"top_k": 8, "sources": ["documents", "semantic_memory"], "min_score": 0.25})
        elif agent_type == "data":
            ds = ctx.data_source_context
            params["data_source_id"] = ds.get("data_source_id", "")
            params["database"] = ds.get("database", "")
            params["schema"] = ds.get("schema", "")

        task = ExecutionTask(
            task_id="force_1",
            capability_type=capability_type,
            query=query,
            params=params,
            priority="high",
            reason=f"force_mode={ctx.force_mode}",
        )

        return ExecutionPlan(
            rewritten_query=query,
            intent_category=ctx.force_mode or "general",
            required_capabilities=[capability_type],
            subtasks=[task],
            merge_strategy="direct",
            risk_level="low",
            metadata={"force_mode": ctx.force_mode},
        )

    async def _plan_via_llm(
        self,
        query: str,
        ctx: RuntimeContext,
        understanding: UnderstandingResult | None = None,
    ) -> ExecutionPlan:
        from kernel.runtime.objects import ExecutionPlan, ExecutionTask

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
                max_tokens=1200,
            )
            text = (resp.content or "").strip()
        except Exception as exc:
            logger.error("CognitivePlanner LLM call failed", error=str(exc))
            return self._fallback_execution_plan(query, ctx, understanding=understanding)

        return self._parse_plan(text, query, ctx, understanding=understanding)

    def _build_system_prompt(
        self, ctx: RuntimeContext, understanding: UnderstandingResult | None
    ) -> str:
        agents_desc = self._format_available_agents()
        data_source_info = self._format_data_source(ctx)

        understanding_block = ""
        if understanding and understanding.explicit_goal:
            understanding_block = f"""
## 任务理解（来自 UnderstandingEngine）
- 明确目标: {understanding.explicit_goal}
- 隐含需求: {understanding.hidden_goal or '无'}
- 实体: {json.dumps(understanding.entities, ensure_ascii=False) if understanding.entities else '无'}
- 约束: {', '.join(understanding.constraints) if understanding.constraints else '无'}
- 歧义: {understanding.ambiguity or '无'}
- 风险级别: {understanding.risk_level}
- 预期输出: {understanding.expected_output_type}
- 推荐能力: {', '.join(understanding.required_capabilities) if understanding.required_capabilities else '待定'}
- 执行策略: {understanding.execution_strategy}
- 完成标准: {understanding.completion_criteria or '待定'}
"""

        return f"""你是 OpenTrace Cognitive Planner — 整个系统的中央认知规划器。

你的职责：**一次性生成完整执行图**，不做增量规划，不做运行时试探。

## 可用能力（Capability）
{agents_desc}

## 数据源
{data_source_info}
{understanding_block}
## 规划原则
1. **Runtime First**: 你决定一切，执行器只负责执行，不允许自主 fallback
2. **Planning First**: 一次规划到位，不要"先试A不行再补B"
3. **Evidence First**: 任务输出是 Evidence，不是原始文本
4. **Capability First**: 按 capability_type 分配（如 data.query, web.search），不按 agent_type
5. 设置依赖关系（depends_on），让并行能力并发执行
6. 评估风险级别（low/medium/high）和完成标准

## 输出格式（纯 JSON，无 markdown 包裹）
{{
  "rewritten_query": "消解指代后的完整查询",
  "intent_category": "data|rag|web|tool|general|mixed",
  "understanding_summary": "对任务的一句话总结",
  "risk_level": "low|medium|high",
  "completion_criteria": "什么算完成？",
  "required_capabilities": ["data.query", "web.search"],
  "subtasks": [
    {{
      "id": "task_1",
      "capability_type": "data.query|web.search|rag.retrieve|tool.datetime|python.execute|chart.generate|memory.retrieve",
      "query": "子任务查询文本",
      "params": {{}},
      "depends_on": [],
      "priority": "high|normal|low",
      "reason": "为什么需要这个子任务",
      "expected_evidence_type": "text|table|chart|code"
    }}
  ],
  "merge_strategy": "union|compare|prioritized"
}}"""

    def _build_user_prompt(
        self,
        query: str,
        ctx: RuntimeContext,
        understanding: UnderstandingResult | None,
    ) -> str:
        parts: list[str] = [f"## 用户提问\n{query}"]

        if ctx.conversation_history:
            recent = ctx.conversation_history[-6:]
            history_text = "\n".join(
                f"[{h.get('role', '?')}]: {str(h.get('content', ''))[:300]}"
                for h in recent
            )
            parts.append(f"## 最近对话历史\n{history_text}")

        if ctx.memory_context:
            parts.append(f"## 相关记忆\n{ctx.memory_context[:1500]}")

        if ctx.preference_context_block:
            parts.append(f"## 用户偏好\n{ctx.preference_context_block[:1000]}")

        ds = ctx.data_source_context
        if ds.get("data_source_id"):
            ds_text = (
                f"已绑定数据源: id={ds.get('data_source_id')}, "
                f"name={ds.get('data_source_name')}, database={ds.get('database')}, "
                f"source_type={ds.get('source_type')}"
            )
            schema = ds.get("schema", "")
            if schema:
                ds_text += f"\nSchema摘要: {str(schema)[:2000]}"
            parts.append(f"## 数据源\n{ds_text}")

        if ctx.attachment_contexts:
            att_text = "\n".join(
                f"- {a.get('name', 'unknown')}: {str(a.get('content_summary', ''))[:500]}"
                for a in ctx.attachment_contexts
            )
            if att_text:
                parts.append(f"## 附件内容\n{att_text}")

        if ctx.enabled_skills:
            parts.append(f"## 启用的技能\n{', '.join(ctx.enabled_skills)}")

        return "\n\n".join(parts)

    def _parse_plan(
        self,
        text: str,
        query: str,
        ctx: RuntimeContext,
        understanding: UnderstandingResult | None = None,
    ) -> ExecutionPlan:
        from kernel.runtime.objects import ExecutionPlan, ExecutionTask

        text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        text = re.sub(r"\n?\s*```\s*$", "", text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("CognitivePlanner JSON parse failed", raw=text[:200])
            return self._fallback_execution_plan(query, ctx, understanding=understanding)

        if not isinstance(data, dict) or "subtasks" not in data:
            return self._fallback_execution_plan(query, ctx, understanding=understanding)

        subtasks_raw = data.get("subtasks", [])
        if not isinstance(subtasks_raw, list) or not subtasks_raw:
            return self._fallback_execution_plan(query, ctx, understanding=understanding)

        subtasks: list[ExecutionTask] = []
        for i, st in enumerate(subtasks_raw):
            if not isinstance(st, dict):
                continue
            capability_type = str(st.get("capability_type", st.get("agent_type", "rag.retrieve")))
            sub_query = str(st.get("query", query))
            params = dict(st.get("params", {}) or {})
            params.setdefault("session_id", ctx.session_id)
            params.setdefault("user_id", ctx.user_id)

            subtasks.append(ExecutionTask(
                task_id=str(st.get("id", f"task_{i}")),
                capability_type=capability_type,
                query=sub_query,
                params=params,
                depends_on=list(st.get("depends_on", []) or []),
                priority=str(st.get("priority", "normal")),
                reason=str(st.get("reason", "")),
                expected_evidence_type=str(st.get("expected_evidence_type", "text")),
            ))

        plan = ExecutionPlan(
            rewritten_query=str(data.get("rewritten_query", query)),
            intent_category=str(data.get("intent_category", "general")),
            understanding_summary=str(data.get("understanding_summary", "")),
            required_capabilities=list(data.get("required_capabilities", []) or []),
            subtasks=subtasks,
            merge_strategy=str(data.get("merge_strategy", "union")),
            risk_level=str(data.get("risk_level", "low")),
            completion_criteria=str(data.get("completion_criteria", "")),
        )

        if understanding and not (plan.understanding_summary or "").strip():
            plan.understanding_summary = understanding.explicit_goal or ""
            if understanding.required_capabilities:
                plan.required_capabilities = list(understanding.required_capabilities)

        logger.info(
            "CognitivePlanner plan generated",
            subtask_count=len(subtasks),
            capabilities=[s.capability_type for s in subtasks],
            merge_strategy=plan.merge_strategy,
            risk_level=plan.risk_level,
        )

        return plan

    def _fallback_execution_plan(
        self,
        query: str,
        ctx: RuntimeContext,
        understanding: UnderstandingResult | None = None,
    ) -> ExecutionPlan:
        from kernel.runtime.objects import ExecutionPlan, ExecutionTask

        caps = (
            list(understanding.required_capabilities)
            if understanding and understanding.required_capabilities
            else ["rag.retrieve"]
        )
        cap0 = caps[0] if caps else "rag.retrieve"
        summary = (understanding.explicit_goal or "") if understanding else ""
        return ExecutionPlan(
            rewritten_query=query,
            intent_category=getattr(understanding, "domain", None) or "general",
            understanding_summary=summary,
            required_capabilities=caps,
            subtasks=[
                ExecutionTask(
                    task_id="fallback_1",
                    capability_type=cap0,
                    query=query,
                    params={
                        "session_id": ctx.session_id,
                        "user_id": ctx.user_id,
                    },
                    priority="normal",
                    reason="fallback: LLM plan parse failed",
                )
            ],
            merge_strategy="direct",
            risk_level=getattr(understanding, "risk_level", None) or "low",
            completion_criteria=getattr(understanding, "completion_criteria", None) or "",
        )

    # ── Helpers (reuse from UnifiedOrchestrator) ──────────────────────────

    def _format_available_agents(self) -> str:
        try:
            if self._capability_registry:
                agents = self._capability_registry.list_agents()
                if agents:
                    lines = []
                    for name in agents:
                        try:
                            cap = self._capability_registry.get(name)
                            desc = cap.description if cap else ""
                        except Exception:
                            desc = ""
                        lines.append(f"- **{name}**: {desc}")
                    return "\n".join(lines)
        except Exception as exc:
            logger.debug("orchestrator_v2_format_agents_skipped", error=str(exc))

        return """- **data**: 结构化数据查询（Text2SQL）→ capability: data.query
- **rag**: 内部文档 + 记忆检索 → capability: rag.retrieve
- **web**: 联网搜索实时信息 → capability: web.search
- **tool**: 工具调用（时间、天气、计算器）→ capability: tool.*
- **skills**: 专业技能调用 → capability: skill.invoke
- **rule_engine**: 产品/规则查询 → capability: rule.lookup
- **vision**: 图像/图表理解 → capability: vision.analyze"""

    def _format_data_source(self, ctx: RuntimeContext) -> str:
        ds = ctx.data_source_context
        if not ds.get("data_source_id"):
            return "未绑定数据源。如果问题涉及数据查询，需要使用 rag.retrieve 或 web.search。"
        return (
            f"已绑定数据源：{ds.get('data_source_name', 'unknown')} "
            f"(id={ds.get('data_source_id')}, database={ds.get('database', 'unknown')}, "
            f"source_type={ds.get('source_type', 'unknown')})"
        )


def _agent_to_capability(agent_type: str) -> str:
    """Map legacy agent_type to capability_type."""
    mapping = {
        "data": "data.query",
        "rag": "rag.retrieve",
        "web": "web.search",
        "tool": "tool.datetime",
        "skills": "skill.invoke",
        "rule_engine": "rule.lookup",
        "vision": "vision.analyze",
    }
    return mapping.get(agent_type, agent_type)
