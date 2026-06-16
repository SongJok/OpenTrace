"""
认知执行体 — 认知运行时管线的唯一入口。

编排完整认知流水线（V2）：
  改写 → 理解 → 策略
  → 认知规划 V2 → 策略构建 → 执行投影
  → 执行运行时 → 证据总线（含生命周期）→ 证据排序
  → 融合 V2 → 批评 → 制品合成
  → 工作区 + 记忆织网 + 真值维护

模块间通信均经 RuntimeContext + RuntimeEventStore。
各阶段边界记录提示词快照与运行时快照，供确定性回放与审计。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from infra.config.settings import settings
from infra.observability.logger import get_logger
from kernel.runtime.governance_hooks import degrade_ctx
from kernel.cognitive_controls import (
    CognitiveBudget,
    IntentLock,
    apply_intent_lock_to_context,
    classify_intent,
    direct_answer_for_intent,
    passes_relevance_anchor,
)

logger = get_logger(__name__)


class CognitiveExecutive:
    """认知执行中枢 — 所有请求的统一入口。

    请求经此完成一次认知决策（CognitivePlan），投影为 ExecutionPlan 后由运行时执行。
    无自主 Agent 回退、无分散认知逻辑。
    模块间仅通过 RuntimeContext 通信，禁止跨模块直接 import。
    """

    def __init__(self) -> None:
        self._rewrite_engine: Any = None
        self._understanding_engine: Any = None
        self._cognitive_planner: Any = None
        self._cognitive_planner_v2: Any = None
        self._strategy_builder: Any = None
        self._capability_graph_builder: Any = None
        self._execution_runtime: Any = None
        self._evidence_bus: Any = None
        self._fusion_engine: Any = None
        self._critic_engine: Any = None
        self._policy_engine: Any = None
        # 上下文压缩
        self._context_compressor: Any = None
        self._context_ranker: Any = None
        # 回放 / 审计
        self._runtime_snapshots: Any = None
        self._trace: Any = None

    async def execute(
        self,
        query: str,
        ctx: Any,  # 运行时上下文
        event_cb: Callable | None = None,
    ) -> CognitiveExecutiveResult:
        """执行完整认知流水线。

        Args:
            query: 用户查询（可为原始或预处理文本）
            ctx: 含会话/记忆/偏好的 RuntimeContext
            event_cb: 可选，流式进度回调
        """
        t_start = time.time()
        agent_errors: list[str] = []
        goal_hooks = None
        try:
            from kernel.goal.goal_runtime_hooks import GoalRuntimeHooks

            goal_hooks = GoalRuntimeHooks.from_context(ctx)
            if goal_hooks:
                goal_hooks.on_phase("init", "execute_start")
        except Exception as exc:
            degrade_ctx(ctx, subsystem="goal_runtime_hooks", detail="from_context", exc=exc)
            goal_hooks = None
        self._runtime_fabric_evolve(ctx, phase="init")
        intent_payload = (getattr(ctx, "metadata", None) or {}).get("intent_lock")
        if isinstance(intent_payload, dict) and intent_payload.get("task_type"):
            # 复用 kernel 已计算好的 intent_lock，不重新 classify
            budget_raw = intent_payload.get("cognitive_budget", {}) or {}
            lock = IntentLock(
                raw_user_query=intent_payload.get("raw_user_query", query),
                normalized_query=intent_payload.get("normalized_query", query),
                protected_intent=intent_payload.get("protected_intent", query),
                task_type=intent_payload.get("task_type", "general_qa"),
                complexity_level=intent_payload.get("complexity_level", "L1"),
                allowed_capabilities=intent_payload.get("allowed_capabilities", []),
                disallowed_capabilities=intent_payload.get("disallowed_capabilities", []),
                confidence=float(intent_payload.get("confidence", 0.72)),
                cognitive_budget=CognitiveBudget(
                    max_planning_depth=int(budget_raw.get("max_planning_depth", 1)),
                    max_capabilities=int(budget_raw.get("max_capabilities", 1)),
                    max_replans=int(budget_raw.get("max_replans", 0)),
                    max_memory_tokens=int(budget_raw.get("max_memory_tokens", 0)),
                    max_context_expansion=int(budget_raw.get("max_context_expansion", 256)),
                    max_reasoning_steps=int(budget_raw.get("max_reasoning_steps", 2)),
                    memory_injection=bool(budget_raw.get("memory_injection", False)),
                    workspace_context=bool(budget_raw.get("workspace_context", False)),
                    critic=bool(budget_raw.get("critic", False)),
                ),
                relevance_threshold=float(intent_payload.get("relevance_threshold", 0.35)),
            )
            apply_intent_lock_to_context(ctx, lock)
        else:
            conv_state = getattr(ctx, "conversation_state", None)
            lock = classify_intent(
                query,
                getattr(ctx, "force_mode", None),
                prior_intent=getattr(conv_state, "active_intent", None) if conv_state else None,
                prior_domain=getattr(conv_state, "active_domain", None) if conv_state else None,
                conversation_phase=getattr(conv_state, "conversation_phase", None) if conv_state else None,
            )
            apply_intent_lock_to_context(ctx, lock)

        direct_answer = direct_answer_for_intent(lock)
        if direct_answer and not getattr(ctx, "force_mode", None):
            return CognitiveExecutiveResult(
                answer=direct_answer,
                risk_level="low",
                rewrite_trace="intent_lock_direct",
            )

        # ── 轨迹初始化 ──
        if settings.kernel_runtime_replay_enabled:
            self._ensure_trace()
            self._trace.request_id = ctx.request_id
            self._trace.session_id = ctx.session_id
            self._trace.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 1：查询改写
        # ══════════════════════════════════════════════════════════════════════
        canonical_query = query
        rewrite_trace = ""
        if settings.kernel_runtime_rewrite_enabled:
            self._ensure_rewrite_engine()
            canonical = await self._rewrite_engine.rewrite(query, ctx)
            canonical_query = canonical.canonical_query
            rewrite_trace = canonical.rewrite_trace

        self._capture_snapshot("post_rewrite", ctx, query=query, rewritten_query=canonical_query)

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 2：理解
        # ══════════════════════════════════════════════════════════════════════
        understanding = None
        if settings.kernel_runtime_understanding_enabled:
            self._ensure_understanding_engine()
            from kernel.runtime.objects import RuntimeCanonicalQuery as RCQ
            canonical_obj = RCQ(
                raw_query=getattr(ctx, "raw_user_query", "") or query,
                normalized_query=canonical_query,
                protected_intent=getattr(ctx, "protected_intent", "") or query,
                canonical_query=canonical_query,
                original_query=query,
            )
            understanding = await self._understanding_engine.understand(canonical_obj, ctx)

        self._capture_snapshot("post_understanding", ctx,
            query=query, rewritten_query=canonical_query,
            understanding_summary={
                "goal": understanding.explicit_goal if understanding else "",
                "risk": understanding.risk_level if understanding else "",
            }
        )

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 3：策略检查
        # ══════════════════════════════════════════════════════════════════════
        try:
            from kernel.runtime.policy import policy_engine
            policy_decision = await policy_engine.evaluate(ctx)
            if not policy_decision.allowed:
                return CognitiveExecutiveResult(
                    answer=f"请求被策略拒绝: {policy_decision.reason}",
                    risk_level="critical",
                    policy_denied=True,
                )
        except Exception as exc:
            logger.debug("Policy check skipped", error=str(exc))

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 3.5：上下文压缩（抑制提示词膨胀）
        # ══════════════════════════════════════════════════════════════════════
        if settings.kernel_context_compressor_enabled:
            budget = getattr(ctx, "cognitive_budget", {}) or {}
            if int(budget.get("max_context_expansion", 0) or 0) > 0:
                self.compress_context(ctx, canonical_query)

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 4：认知规划（V2 三层流水线）
        # ══════════════════════════════════════════════════════════════════════
        use_v2 = bool(getattr(settings, "kernel_cognitive_planner_v2_enabled", True))
        plan: Any = None
        execution_graph = None
        cognitive_plan: Any = None

        if use_v2:
            from kernel.goal.goal_driven_planner import plan_from_goal_context

            cognitive_plan, plan, execution_graph = await plan_from_goal_context(
                canonical_query, ctx, understanding=understanding
            )
            try:
                from kernel.runtime.capability_governance import apply_governance_with_fallback

                execution_graph = apply_governance_with_fallback(
                    plan,
                    execution_graph,
                    ctx,
                    canonical_query,
                    node_id_prefix="exec_gov_fallback",
                )
            except Exception as exc:
                logger.debug("Capability governance skipped", error=str(exc))
            self._sync_goal_graph_from_runtime_task(ctx, plan)
            self._runtime_fabric_evolve(ctx, phase="plan")
            self._apply_phase_governance(ctx, phase="plan")
            try:
                from kernel.governance.governance_center import get_governance_center

                plan_mut = get_governance_center().evaluate_planning_mutation(ctx)
                if self._apply_policy_mutation(ctx, kind="plan", decision=plan_mut):
                    return CognitiveExecutiveResult(
                        answer="规划策略未通过治理检查。",
                        risk_level="medium",
                        policy_denied=True,
                    )
            except Exception as exc:
                degrade_ctx(ctx, subsystem="governance_center", detail="evaluate_planning_mutation", exc=exc)
            if goal_hooks:
                goal_hooks.on_phase("plan", "execution_planned")

            self._capture_snapshot("post_planning", ctx,
                query=query, rewritten_query=canonical_query,
                cognitive_plan_summary=cognitive_plan.summary(),
                execution_plan_summary={
                    "subtasks": len(plan.subtasks),
                    "risk": plan.risk_level,
                }
            )
        else:
            self._ensure_cognitive_planner()
            plan = await self._cognitive_planner.plan(canonical_query, ctx, understanding=understanding)

        if execution_graph is None and settings.kernel_runtime_capability_graph_enabled:
            self._ensure_capability_graph_builder()
            execution_graph = await self._capability_graph_builder.build(plan)

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 4.5：约束层（确定性护栏，不调用 LLM）
        # ══════════════════════════════════════════════════════════════════════
        if use_v2 and plan is not None:
            try:
                from kernel.runtime.constraint_layer import constraint_layer

                cap_names: list[str] = []
                if execution_graph is not None:
                    cap_names = [
                        getattr(n, "capability_name", "")
                        for n in execution_graph
                        if getattr(n, "capability_name", "")
                    ]
                else:
                    cap_names = [t.capability_type for t in getattr(plan, "subtasks", []) if getattr(t, "capability_type", "")]

                constraint_decision = constraint_layer.evaluate(
                    plan=cognitive_plan if use_v2 else plan,
                    ctx=ctx,
                    capability_names=cap_names,
                )

                if not constraint_decision.allowed:
                    # 尝试一次 replan（将约束反馈注入上下文后重新规划）
                    replan_succeeded = False
                    try:
                        logger.info(
                            "Constraint denied, attempting replan",
                            reason=constraint_decision.reason,
                        )
                        ctx.metadata = ctx.metadata or {}
                        ctx.metadata["constraint_feedback"] = constraint_decision.reason
                        # 标记仅允许 model.answer，强制 planner 使用直接推理
                        ctx.allowed_capabilities = ["model.answer"]
                        ctx.disallowed_capabilities = [
                            "rag.retrieve", "web.search", "data.query",
                            "memory.retrieve", "tool.weather", "tool.datetime",
                            "python.execute", "chart.generate",
                        ]
                        ctx.task_type = "general_qa"

                        from kernel.goal.goal_driven_planner import plan_from_goal_context

                        cognitive_plan_v2, plan_v2, execution_graph_v2 = (
                            await plan_from_goal_context(
                                canonical_query, ctx, understanding=understanding
                            )
                        )

                        cap_names_v2: list[str] = [
                            getattr(n, "capability_name", "")
                            for n in execution_graph_v2
                            if getattr(n, "capability_name", "")
                        ]
                        constraint_decision_v2 = constraint_layer.evaluate(
                            plan=cognitive_plan_v2,
                            ctx=ctx,
                            capability_names=cap_names_v2,
                        )
                        if constraint_decision_v2.allowed:
                            cognitive_plan = cognitive_plan_v2
                            plan = plan_v2
                            execution_graph = execution_graph_v2
                            constraint_decision = constraint_decision_v2
                            replan_succeeded = True
                            logger.info("Replan succeeded after constraint denial")
                    except Exception as replan_exc:
                        logger.warning("Replan failed", error=str(replan_exc))

                    if not replan_succeeded:
                        # 最终降级：直接 LLM 回答，不使用任何外部能力
                        logger.warning(
                            "Constraint denied, falling back to direct answer",
                            reason=constraint_decision.reason,
                        )
                        return await self._direct_answer_fallback(canonical_query, ctx)

                # 应用约束层修改
                if constraint_decision.modifications:
                    logger.info(
                        "Constraint layer modifications applied",
                        modifications=constraint_decision.modifications,
                        warnings=constraint_decision.warnings,
                    )
                    ctx.metadata = ctx.metadata or {}
                    ctx.metadata["constraint_modifications"] = constraint_decision.modifications
                    ctx.metadata["constraint_warnings"] = constraint_decision.warnings

                if constraint_decision.fallback_strategy == "simplify":
                    plan = self._simplify_plan(plan, constraint_decision)
            except Exception as exc:
                logger.debug("Constraint layer skipped", error=str(exc))

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 5-6：执行
        # ══════════════════════════════════════════════════════════════════════
        self._runtime_fabric_evolve(ctx, phase="execute")
        if self._phase_transition_blocked(ctx):
            return CognitiveExecutiveResult(
                answer="运行时阶段转移违反契约，已中止执行。",
                risk_level="medium",
                policy_denied=True,
            )
        self._apply_execution_guardrails(ctx, plan, execution_graph)
        try:
            from kernel.capability_runtime.dispatch_pipeline import (
                collect_planned_capability_types,
                validate_planned_capabilities,
            )

            planned_caps = collect_planned_capability_types(plan, execution_graph)
            cap_gate = validate_planned_capabilities(planned_caps)
            ctx.metadata = ctx.metadata or {}
            ctx.metadata["capability_contract_gate"] = cap_gate
            if not cap_gate.get("allowed") and bool(
                getattr(settings, "kernel_capability_contract_strict", False)
            ):
                return CognitiveExecutiveResult(
                    answer="能力执行契约未通过，已中止。",
                    risk_level="medium",
                    policy_denied=True,
                )
        except Exception as exc:
            degrade_ctx(ctx, subsystem="capability_contract_gate", detail="validate_planned", exc=exc)
        if goal_hooks:
            goal_hooks.on_phase("execute", "runtime_execute")
        self._ensure_execution_runtime()
        agent_results = await self._execution_runtime.execute(
            plan=plan if not execution_graph else None,
            ctx=ctx,
            event_cb=event_cb,
            capability_executor_mode=settings.kernel_agent_capability_executor_mode,
            execution_graph=execution_graph,
        )
        try:
            from kernel.goal.goal_execution_outcomes import record_goal_execution_outcomes

            record_goal_execution_outcomes(ctx, execution_graph, agent_results)
        except Exception as exc:
            degrade_ctx(ctx, subsystem="goal_execution_outcomes", detail="record_after_execute", exc=exc)

        if getattr(settings, "kernel_refine_replan_enabled", True):
            try:
                from kernel.cognition.planner_facade import RefinementPlanner
                from kernel.refine_planner import RepairStrategy

                plan, agent_results, replanned, refined_info = await RefinementPlanner().maybe_replan_after_failures(
                    canonical_query, plan, agent_results, depth=0
                )
                if replanned and refined_info is not None:
                    ctx.metadata = ctx.metadata or {}
                    ctx.metadata["refine_replan"] = {
                        "strategy": refined_info.repair_strategy.value,
                        "depth": refined_info.depth,
                    }
                    reexec_strategies = {
                        RepairStrategy.RETRY,
                        RepairStrategy.SUBSTITUTE,
                        RepairStrategy.SIMPLIFY,
                        RepairStrategy.PREPEND,
                    }
                    if (
                        getattr(settings, "kernel_refine_reexec_enabled", True)
                        and refined_info.repair_strategy in reexec_strategies
                    ):
                        retry_results = await self._execution_runtime.execute(
                            plan=plan,
                            ctx=ctx,
                            event_cb=event_cb,
                            capability_executor_mode=settings.kernel_agent_capability_executor_mode,
                            execution_graph=None,
                        )
                        if retry_results:
                            agent_results = retry_results
                            ctx.metadata["refine_reexec"] = True
                            try:
                                from kernel.goal.goal_execution_outcomes import (
                                    record_goal_execution_outcomes,
                                )

                                record_goal_execution_outcomes(
                                    ctx, execution_graph, agent_results
                                )
                            except Exception as exc:
                                degrade_ctx(
                                    ctx,
                                    subsystem="goal_execution_outcomes",
                                    detail="record_after_refine_reexec",
                                    exc=exc,
                                )
            except Exception as exc:
                degrade_ctx(ctx, subsystem="refinement_planner", detail="maybe_replan", exc=exc)

        try:
            from kernel.capability_runtime.dispatch_pipeline import (
                collect_executed_capability_types,
                record_capability_outcomes,
                resolve_root_goal_from_ctx,
            )

            root_goal, goal_desc = resolve_root_goal_from_ctx(ctx)
            ctx.metadata = ctx.metadata or {}
            record_capability_outcomes(
                agent_results,
                query_preview=canonical_query,
                root_goal_id=root_goal,
                goal_description=goal_desc,
                metadata_target=ctx.metadata,
                trace_id=str(ctx.metadata.get("request_id") or ""),
                ctx=ctx,
            )
            caps = collect_executed_capability_types(agent_results)
            if caps:
                ctx.metadata = ctx.metadata or {}
                prior = list(ctx.metadata.get("capabilities_used") or [])
                ctx.metadata["capabilities_used"] = list(dict.fromkeys(prior + caps))
                if not ctx.metadata.get("capability_type"):
                    ctx.metadata["capability_type"] = caps[0]
        except Exception as exc:
            degrade_ctx(ctx, subsystem="capability_outcomes", detail="record_capability_outcomes", exc=exc)

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 7：证据收集（含生命周期）
        # ══════════════════════════════════════════════════════════════════════
        self._ensure_evidence_bus()
        await self._evidence_bus.publish_results(agent_results)

        evidence_objects: list[Any] = []
        for r in agent_results:
            if hasattr(r, "evidence_objects") and r.evidence_objects:
                evidence_objects.extend(r.evidence_objects)
            if getattr(r, "status", "") == "error" and getattr(r, "error", ""):
                agent_errors.append(f"{r.agent_type}: {r.error}")
        if not evidence_objects:
            evidence_objects = await self._evidence_bus.collect()

        # 排序并解析证据
        try:
            _resolved = await self._evidence_bus.resolve(canonical_query)
            usable = await self._evidence_bus.get_usable()
            if usable:
                evidence_objects = usable
        except Exception as exc:
            logger.debug("Evidence resolution skipped", error=str(exc))

        self._runtime_fabric_evolve(
            ctx,
            phase="evidence",
            evidence_ref=f"count:{len(evidence_objects)}",
        )
        min_ev = 1 if getattr(plan, "subtasks", None) else 0
        self._apply_phase_governance(
            ctx,
            phase="evidence",
            evidence_count=len(evidence_objects),
            min_evidence=min_ev,
        )
        if bool(getattr(settings, "kernel_evidence_contract_strict", False)):
            from kernel.protocol.behavior_contracts import validate_evidence_contract

            eids = [
                str(getattr(e, "evidence_id", "") or getattr(e, "id", ""))
                for e in evidence_objects
                if getattr(e, "evidence_id", None) or getattr(e, "id", None)
            ]
            ev_violations = validate_evidence_contract(eids, min_count=min_ev)
            ctx.metadata = ctx.metadata or {}
            ctx.metadata["evidence_contract_violations"] = ev_violations
            if ev_violations:
                pol = (ctx.metadata.get("phase_policies") or {}).get("evidence") or {}
                if not pol.get("allow_fusion", True):
                    return CognitiveExecutiveResult(
                        answer="证据契约未满足，无法安全融合回答。",
                        risk_level="medium",
                        policy_denied=True,
                        evidence_objects=evidence_objects,
                    )
        if goal_hooks:
            goal_hooks.on_phase("evidence", f"count={len(evidence_objects)}")
            goal_hooks.record_evidence_ids(evidence_objects)
        try:
            from kernel.goal.goal_evidence_binding import extract_evidence_ids, stamp_evidence_goal_ids
            from kernel.context_fabric_session import sync_evidence_node

            md = getattr(ctx, "metadata", None) or {}
            gg = md.get("goal_graph") or {}
            root = str(gg.get("root_goal_id", "") or getattr(ctx, "request_id", ""))
            stamp_evidence_goal_ids(
                evidence_objects, root_goal_id=root, request_id=str(getattr(ctx, "request_id", ""))
            )
            sid = str(getattr(ctx, "session_id", "") or "")
            eids = extract_evidence_ids(evidence_objects)
            from kernel.runtime.cognitive_state.bus import record_evidence_on_bus

            record_evidence_on_bus(ctx, eids)
            for eid in eids:
                sync_evidence_node(sid, evidence_id=eid, goal_id=root)
                try:
                    from memory.fabric.router_singleton import get_memory_fabric_router

                    get_memory_fabric_router().bind(
                        f"{sid}:{eid}",
                        goal_id=root,
                        evidence_id=eid,
                        salience=0.7,
                        metadata={"session_id": sid, "phase": "evidence"},
                    )
                except Exception as exc:
                    degrade_ctx(ctx, subsystem="memory_fabric", detail="evidence_bind", exc=exc)
        except Exception as exc:
            degrade_ctx(ctx, subsystem="goal_evidence_binding", detail="stamp_and_sync", exc=exc)
        self._capture_snapshot("post_execution", ctx,
            query=query, rewritten_query=canonical_query,
            evidence_count=len(evidence_objects),
            evidence_summary=_count_evidence_by_source(evidence_objects),
        )

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 8：融合
        # ══════════════════════════════════════════════════════════════════════
        hall_pre = 0.0
        try:
            from kernel.governance.governance_center import get_governance_center

            ev_mut = get_governance_center().evaluate_evidence_fusion_mutation(
                evidence_count=len(evidence_objects),
                min_required=min_ev,
                hallucination_risk=hall_pre,
            )
            if self._apply_policy_mutation(ctx, kind="evidence_fusion", decision=ev_mut):
                return CognitiveExecutiveResult(
                    answer="证据融合未通过策略检查。",
                    risk_level="medium",
                    policy_denied=True,
                    evidence_objects=evidence_objects,
                )
        except Exception as exc:
            degrade_ctx(ctx, subsystem="governance_center", detail="evaluate_evidence_fusion", exc=exc)
        self._ensure_fusion_engine()
        fusion_result = await self._fusion_engine.fuse(
            query=canonical_query,
            ctx=ctx,
            evidence_list=evidence_objects,
        )
        if goal_hooks:
            goal_hooks.on_phase("fusion", "merged")

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 9：批评
        # ══════════════════════════════════════════════════════════════════════
        raw_query = getattr(ctx, "raw_user_query", "") or query
        relevance_ok = passes_relevance_anchor(
            raw_query,
            fusion_result.merged_context,
            float(getattr(ctx, "relevance_threshold", 0.35) or 0.35),
        )
        if not relevance_ok and direct_answer:
            fusion_result.merged_context = direct_answer
            fusion_result.confidence = max(float(getattr(fusion_result, "confidence", 0.0) or 0.0), 0.9)
            relevance_ok = True

        self._runtime_fabric_evolve(ctx, phase="fusion")

        critic_result = None
        budget = getattr(ctx, "cognitive_budget", {}) or {}
        if bool(budget.get("critic", True)):
            self._ensure_critic_engine()
            critic_result = await self._critic_engine.evaluate(
                query=canonical_query,
                answer=fusion_result.merged_context,
                evidence_count=len(evidence_objects),
            )

        governance_meta: dict[str, Any] = {}
        if getattr(settings, "kernel_governance_evidence_gate_enabled", True):
            try:
                from kernel.governance.evidence_governor import EvidenceGovernor
                from kernel.protocol.runtime_contract import EvidencePolicy

                min_ev = 1 if getattr(plan, "subtasks", None) else 0
                eg = EvidenceGovernor().evaluate(
                    evidence_count=len(evidence_objects),
                    confidence=float(getattr(fusion_result, "confidence", 0.0) or 0.0),
                    policy=EvidencePolicy(min_evidence_count=min_ev),
                )
                governance_meta["evidence"] = {
                    "passed": eg.passed,
                    "failures": list(eg.failures),
                }
            except Exception as exc:
                logger.debug("Evidence governor skipped", error=str(exc))

        if getattr(settings, "kernel_governance_risk_gate_enabled", True):
            try:
                from kernel.governance.risk_governor import RiskGovernor

                hall = float(getattr(critic_result, "hallucination_risk", 0.0) or 0.0) if critic_result else 0.0
                rg = RiskGovernor().assess(hallucination_risk=hall, policy_denied=False)
                governance_meta["risk"] = {
                    "level": rg.level,
                    "blocked": rg.blocked,
                    "signals": list(rg.signals),
                }
            except Exception as exc:
                logger.debug("Risk governor skipped", error=str(exc))

        if governance_meta:
            ctx.metadata = ctx.metadata or {}
            ctx.metadata["governance"] = governance_meta

        try:
            from kernel.governance.governance_center import get_governance_center

            hall_post = float(
                getattr(critic_result, "hallucination_risk", 0.0) or 0.0
            ) if critic_result else 0.0
            post_fusion = get_governance_center().evaluate_evidence_fusion_mutation(
                evidence_count=len(evidence_objects),
                min_required=min_ev,
                hallucination_risk=hall_post,
            )
            if self._apply_policy_mutation(
                ctx, kind="evidence_fusion_post_critic", decision=post_fusion
            ):
                return CognitiveExecutiveResult(
                    answer="融合结果未通过事后策略检查（幻觉风险过高或证据不足）。",
                    risk_level="high",
                    policy_denied=True,
                    evidence_objects=evidence_objects,
                    fusion_result=fusion_result,
                    critic_result=critic_result,
                )
        except Exception as exc:
            degrade_ctx(ctx, subsystem="governance_center", detail="evaluate_evidence_fusion_post_critic", exc=exc)

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 9.5：能力反馈环 — 从执行结果学习
        # ══════════════════════════════════════════════════════════════════════
        try:
            from kernel.capability_intelligence import (
                CapabilityFeedbackLoop,
                ExecutionRecord,
                _capability_intelligence_enabled,
                _capability_intelligence_phase2_enabled,
                capability_profiler,
            )
            from kernel.runtime.capability import capability_registry

            if _capability_intelligence_enabled():
                capability_profiler.build_profiles(capability_registry)
                feedback_loop = CapabilityFeedbackLoop(capability_profiler)
                now = time.time()
                recorded_caps: list[ExecutionRecord] = []

                for ev in evidence_objects:
                    cap_type = _infer_capability_from_evidence(ev)
                    if cap_type:
                        record = ExecutionRecord(
                            capability_type=cap_type,
                            query_preview=(getattr(ev, "content", "") or "")[:80],
                            success=getattr(ev, "state", "") in ("validated", "ranked"),
                            latency_ms=getattr(ev, "metadata", {}).get("latency_ms", 0) if hasattr(ev, "metadata") else 0,
                            evidence_quality=getattr(ev, "credibility_score", 0.0),
                            timestamp=now,
                        )
                        feedback_loop.record(record)
                        recorded_caps.append(record)

                # 第二阶段：写入 execution_memory、strategy_memory 并触发演化
                if _capability_intelligence_phase2_enabled():
                    from kernel.capability_intelligence.evolution import (
                        _ensure_evolution_engine,
                    )
                    from kernel.capability_intelligence.execution_memory import execution_memory
                    from kernel.capability_intelligence.strategy_memory import (
                        StrategyRecord,
                        strategy_memory,
                    )

                    # 记录单次执行
                    for rec in recorded_caps:
                        execution_memory.record(rec)

                    # 从执行图依赖记录顺序模式
                    if execution_graph is not None:
                        for node in execution_graph:
                            for dep_id in getattr(node, "depends_on", []):
                                dep_cap = _infer_capability_from_evidence(
                                    next(
                                        (n for n in execution_graph if getattr(n, "node_id", "") == dep_id),
                                        None,
                                    )
                                )
                                cur_cap = _infer_capability_from_evidence(node)
                                if dep_cap and cur_cap:
                                    dep_record = next(
                                        (r for r in recorded_caps if r.capability_type == dep_cap), None
                                    )
                                    cur_record = next(
                                        (r for r in recorded_caps if r.capability_type == cur_cap), None
                                    )
                                    if dep_record and cur_record:
                                        execution_memory.record_sequential(dep_record, cur_record)

                    # 记录策略结果
                    domain = getattr(understanding, "domain", "general") if understanding else "general"
                    caps_used = sorted(set(r.capability_type for r in recorded_caps))
                    strategy_type = getattr(cognitive_plan, "execution_strategy", "direct") if use_v2 else "direct"
                    turn_success = bool(
                        getattr(critic_result, "passed", False)
                    ) if critic_result else False
                    total_latency = int((time.time() - t_start) * 1000)

                    strategy_memory.record(StrategyRecord(
                        strategy_type=strategy_type,
                        capabilities_used=caps_used,
                        query_domain=domain,
                        query_preview=query[:80],
                        success=all(r.success for r in recorded_caps) if recorded_caps else True,
                        turn_success=turn_success,
                        latency_ms=total_latency,
                        timestamp=now,
                    ))

                    # 触发演化分析
                    reasoner = capability_profiler.get_reasoner()
                    evo_interval = getattr(settings, "kernel_capability_evolution_interval", 10)
                    evo = _ensure_evolution_engine(
                        execution_memory=execution_memory,
                        strategy_memory=strategy_memory,
                        reasoner=reasoner,
                        interval=evo_interval,
                    )
                    insights = evo.on_turn_complete()
                    if insights:
                        logger.debug("Evolution insights generated", count=len(insights))
                    ctx.metadata = ctx.metadata or {}
                    ctx.metadata["capability_evolution"] = {
                        "recorded": caps_used,
                        "insights": [
                            {
                                "insight_type": i.insight_type,
                                "capability_type": i.capability_type,
                                "severity": i.severity,
                                "message": i.message[:200],
                            }
                            for i in insights
                        ],
                        "turn_count": evo._turn_count,
                        "source": "cognitive_executive",
                    }
        except Exception as exc:
            degrade_ctx(ctx, subsystem="capability_feedback", detail="feedback_loop", exc=exc)

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 9.6：失败记忆记录
        # ══════════════════════════════════════════════════════════════════════
        try:
            from kernel.capability_intelligence.failure_memory import failure_memory

            for r in agent_results:
                if getattr(r, "status", "") == "error":
                    cap_type = _infer_capability_from_evidence(r)
                    if not cap_type:
                        cap_type = getattr(r, "agent_type", "unknown")
                    failure_memory.record_from_result(
                        capability_type=cap_type,
                        query=canonical_query,
                        success=False,
                        error_msg=getattr(r, "error", "") or "unknown error",
                    )

            if critic_result and not getattr(critic_result, "passed", True):
                failure_memory.record_from_result(
                    capability_type="critic",
                    query=canonical_query,
                    success=False,
                    error_msg="Critic score below threshold",
                    critic_score=getattr(critic_result, "factuality", 0.0),
                )

            # 定期清理过期失败记录
            failure_memory.clear_stale()
        except Exception as exc:
            degrade_ctx(ctx, subsystem="failure_memory", detail="record_failures", exc=exc)

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 9.7：认知迭代（Reflection → Replan → 可选重执行）
        # ══════════════════════════════════════════════════════════════════════
        if getattr(settings, "kernel_cognitive_iteration_enabled", True):
            try:
                from kernel.runtime.cognitive_iteration import maybe_executive_replan

                plan, agent_results, iter_replanned = await maybe_executive_replan(
                    canonical_query=canonical_query,
                    ctx=ctx,
                    plan=plan,
                    agent_results=agent_results,
                    critic_result=critic_result,
                    evidence_objects=evidence_objects,
                    execution_runtime=self._execution_runtime,
                    event_cb=event_cb,
                    fusion_confidence=float(
                        getattr(fusion_result, "confidence", 0.0) or 0.0
                    ),
                )
                if iter_replanned:
                    self._ensure_fusion_engine()
                    fusion_result = await self._fusion_engine.fuse(
                        query=canonical_query,
                        ctx=ctx,
                        evidence_list=evidence_objects,
                    )
                    if bool((getattr(ctx, "cognitive_budget", {}) or {}).get("critic", True)):
                        self._ensure_critic_engine()
                        critic_result = await self._critic_engine.evaluate(
                            query=canonical_query,
                            answer=fusion_result.merged_context,
                            evidence_count=len(evidence_objects),
                        )
            except Exception as exc:
                degrade_ctx(ctx, subsystem="cognitive_iteration", detail="maybe_replan", exc=exc)

        try:
            from kernel.capability_intelligence.strategy_pattern import (
                planner_enabled,
                record_turn_pattern,
            )

            if planner_enabled():
                domain = (
                    getattr(understanding, "domain", "general") if understanding else "general"
                )
                caps_used = sorted(
                    {
                        str(getattr(r, "agent_type", "") or "")
                        for r in agent_results
                        if getattr(r, "agent_type", None)
                    }
                )
                turn_ok = bool(
                    getattr(critic_result, "passed", True) if critic_result else True
                )
                pat = record_turn_pattern(
                    intent_category=str(domain),
                    capabilities_used=caps_used,
                    strategy_type=(
                        getattr(cognitive_plan, "execution_strategy", "direct")
                        if use_v2 and cognitive_plan is not None
                        else "direct"
                    ),
                    success=turn_ok,
                    latency_ms=int((time.time() - t_start) * 1000),
                    query_preview=canonical_query,
                )
                ctx.metadata = ctx.metadata or {}
                ctx.metadata["strategy_pattern_recorded"] = pat.to_dict()
        except Exception as exc:
            degrade_ctx(ctx, subsystem="strategy_pattern", detail="record_turn", exc=exc)

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 10：制品合成
        # ══════════════════════════════════════════════════════════════════════
        artifact = None
        if settings.kernel_runtime_artifact_composer_enabled:
            try:
                from kernel.runtime.artifact_composer import ArtifactComposer
                composer = ArtifactComposer()
                artifact = composer.compose(
                    query=query,
                    fusion_result=fusion_result,
                    critic_result=critic_result,
                    session_id=ctx.session_id,
                    intent_category=getattr(plan, "intent_category", ""),
                )
                if settings.kernel_runtime_workspace_enabled:
                    from kernel.runtime.workspace import WorkspaceManager
                    wm = WorkspaceManager()
                    ws = wm.get_or_create(ctx.session_id)
                    ws.add_artifact(artifact)
            except Exception as exc:
                logger.debug("Artifact composition skipped", error=str(exc))

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 11：归档本回合证据
        # ══════════════════════════════════════════════════════════════════════
        try:
            await self._evidence_bus.archive_turn()
        except Exception as exc:
            degrade_ctx(ctx, subsystem="evidence_bus", detail="archive_turn", exc=exc)

        # ── 轨迹收尾 ──
        if settings.kernel_runtime_replay_enabled and self._trace:
            self._trace.ended_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._trace.total_duration_ms = int((time.time() - t_start) * 1000)
        if settings.kernel_runtime_replay_enabled:
            try:
                from kernel.goal.goal_replay import snapshot_goal_for_replay

                ctx.metadata = ctx.metadata or {}
                ctx.metadata["goal_replay_snapshot"] = snapshot_goal_for_replay(ctx)
            except Exception as exc:
                degrade_ctx(ctx, subsystem="goal_replay", detail="snapshot", exc=exc)

        # ══════════════════════════════════════════════════════════════════════
        # 阶段 11.5：执行推理轨迹
        # ══════════════════════════════════════════════════════════════════════
        execution_reasoning = None
        try:
            from kernel.runtime.execution_reasoning import execution_reasoning_builder

            # 从策略收集能力分配
            assignments_list: list[Any] = []
            if use_v2 and cognitive_plan is not None:
                try:
                    strategy = cognitive_plan.cognitive_graph
                    for gap in strategy.information_gaps:
                        assignments_list.append(type("_Assign", (), {
                            "capability_type": gap.suggested_source or "unknown",
                            "capability_name": gap.suggested_source or "unknown",
                            "score": 0.0,
                            "depends_on": [],
                            "expected_output": gap.gap_type,
                        })())
                except Exception as exc:
                    degrade_ctx(ctx, subsystem="execution_reasoning", detail="gap_assignments", exc=exc)

            # 构建推理轨迹
            execution_reasoning = execution_reasoning_builder.build(
                query=canonical_query,
                request_id=ctx.request_id,
                session_id=ctx.session_id,
                capability_assignments=assignments_list if assignments_list else None,
                constraint_modifications=(
                    ctx.metadata.get("constraint_modifications", []) if ctx.metadata else []
                ),
                skipped=[
                    c.get("capability", "") for c in (
                        ctx.metadata.get("constraint_warnings", []) if ctx.metadata else []
                    )
                ],
            )
        except Exception as exc:
            degrade_ctx(ctx, subsystem="execution_reasoning", detail="build_trajectory", exc=exc)

        try:
            from kernel.governance.governance_center import get_governance_center

            preview = (fusion_result.merged_context or "")[:200]
            mem_mut = get_governance_center().evaluate_memory_mutation(
                proposed_tokens=max(1, len(preview) // 4),
                pollution_risk=float(
                    (getattr(ctx, "metadata", None) or {})
                    .get("semantic_observability", {})
                    .get("memory_pollution_risk", 0.0)
                    or 0.0
                ),
            )
            if self._apply_policy_mutation(ctx, kind="memory_write", decision=mem_mut):
                return CognitiveExecutiveResult(
                    answer="记忆写入未通过策略检查。",
                    risk_level="medium",
                    policy_denied=True,
                    evidence_objects=evidence_objects,
                )
        except Exception as exc:
            degrade_ctx(ctx, subsystem="governance_center", detail="evaluate_memory_mutation", exc=exc)
        try:
            from kernel.goal.goal_memory_binding import bind_from_runtime_context

            bind_from_runtime_context(
                ctx,
                answer_preview=(fusion_result.merged_context or "")[:200],
            )
        except Exception as exc:
            degrade_ctx(ctx, subsystem="goal_memory_binding", detail="bind_from_runtime_context", exc=exc)
        self._apply_phase_governance(ctx, phase="memory")
        self._runtime_fabric_evolve(ctx, phase="fusion")
        try:
            from memory.fabric.memory_evolution import evolve_session_memory

            md = getattr(ctx, "metadata", None) or {}
            gg = md.get("goal_graph") or {}
            evolve_session_memory(
                str(getattr(ctx, "session_id", "") or ""),
                request_id=str(getattr(ctx, "request_id", "") or ""),
                goal_id=str(gg.get("root_goal_id", "") or ""),
                relations_added=1,
            )
        except Exception as exc:
            degrade_ctx(ctx, subsystem="memory_evolution", detail="evolve_session_memory", exc=exc)

        self._runtime_fabric_evolve(ctx, phase="complete")
        if goal_hooks:
            passed = getattr(critic_result, "passed", True) if critic_result else True
            goal_hooks.on_phase("complete" if passed else "failed", "critic_done")
            goal_hooks.snapshot_metrics(
                hallucination_risk=float(
                    getattr(critic_result, "hallucination_risk", 0.0) or 0.0
                )
                if critic_result
                else 0.0,
                evidence_count=float(len(evidence_objects)),
                fusion_confidence=float(
                    getattr(fusion_result, "confidence", 0.0) or 0.0
                ),
            )

        try:
            from kernel.goal.goal_progress import persist_goal_progress, sync_goal_lifecycle_from_metadata

            sync_goal_lifecycle_from_metadata(ctx)
            await persist_goal_progress(ctx)
        except Exception as exc:
            degrade_ctx(ctx, subsystem="goal_progress", detail="persist", exc=exc)

        # ── 组装返回结果 ──
        answer = fusion_result.merged_context
        if not answer and agent_errors:
            answer = "无法完成请求：" + "; ".join(agent_errors[:3])

        return CognitiveExecutiveResult(
            answer=answer,
            evidence_objects=evidence_objects,
            artifact=artifact,
            plan=plan,
            fusion_result=fusion_result,
            critic_result=critic_result,
            rewrite_trace=rewrite_trace,
            understanding=understanding,
            risk_level=getattr(plan, "risk_level", "low"),
            execution_reasoning=execution_reasoning,
        )

    def _sync_goal_graph_from_runtime_task(self, ctx: Any, plan: Any) -> None:
        """将执行子任务合并进 RuntimeTask 上的 goal_graph（由网关注入）。"""
        ctx.metadata = ctx.metadata or {}
        rt = ctx.metadata.get("runtime_task")
        if rt is None or not getattr(rt, "goal_graph", None):
            return
        graph = rt.goal_graph
        root_id = graph.root_goal_id
        from kernel.protocol.runtime_contract import Goal

        existing_sub = {g.goal_id for g in graph.goals if g.parent_id == root_id}
        for i, st in enumerate(getattr(plan, "subtasks", []) or []):
            cap = getattr(st, "capability_type", "") or getattr(st, "agent_type", "")
            desc = getattr(st, "description", "") or getattr(st, "query", "") or cap
            gid = f"{root_id}:exec:{i+1}"
            if gid in existing_sub:
                continue
            graph.add_goal(
                Goal(
                    goal_id=gid,
                    description=str(desc)[:500],
                    parent_id=root_id,
                    priority=i,
                    metadata={"capability_type": cap, "role": "execution_subtask"},
                )
            )
        ctx.metadata["goal_graph"] = graph.to_dict()

    def _policy_mutation_fail_closed(self, ctx: Any) -> bool:
        """Staging defaults to fail-closed on policy mutations; prod uses explicit flag."""
        if bool(getattr(settings, "kernel_policy_mutation_fail_closed", False)):
            return True
        return str(getattr(settings, "app_env", "")) == "staging"

    def _apply_policy_mutation(
        self,
        ctx: Any,
        *,
        kind: str,
        decision: dict[str, Any],
    ) -> bool:
        """Record mutation policy; return True if caller should abort (denied + fail-closed)."""
        ctx.metadata = ctx.metadata or {}
        bucket = dict(ctx.metadata.get("policy_mutations") or {})
        bucket[kind] = decision
        ctx.metadata["policy_mutations"] = bucket
        if not decision.get("allowed", True) and self._policy_mutation_fail_closed(ctx):
            ctx.metadata["policy_denied"] = True
            ctx.metadata["policy_denied_reason"] = kind
            return True
        return False

    def _phase_transition_blocked(self, ctx: Any) -> bool:
        strict = bool(getattr(settings, "kernel_runtime_phase_transition_strict", False))
        if not strict and str(getattr(settings, "app_env", "")) == "staging":
            strict = bool(getattr(settings, "kernel_staging_phase_transition_strict", True))
        if not strict:
            return False
        md = getattr(ctx, "metadata", None) or {}
        return bool(md.get("phase_transition_violations"))

    def _runtime_fabric_evolve(
        self,
        ctx: Any,
        *,
        phase: str = "",
        evidence_ref: str = "",
        memory_ref: str = "",
    ) -> None:
        try:
            from kernel.context_fabric import get_context_fabric

            md = getattr(ctx, "metadata", None) or {}
            gg = md.get("goal_graph") or {}
            root = str(gg.get("root_goal_id", "") or getattr(ctx, "request_id", ""))
            sid = str(getattr(ctx, "session_id", "") or "")
            prev = str(md.get("runtime_phase", "init") or "init")
            if phase:
                from kernel.protocol.behavior_contracts import enforce_phase_transition

                strict = bool(getattr(settings, "kernel_runtime_phase_transition_strict", False))
                if not strict and str(getattr(settings, "app_env", "")) == "staging":
                    strict = bool(
                        getattr(settings, "kernel_staging_phase_transition_strict", True)
                    )
                phase_v = enforce_phase_transition(prev, phase, strict=strict)
                if phase_v:
                    violations = list(md.get("phase_transition_violations") or [])
                    violations.extend(phase_v)
                    md["phase_transition_violations"] = violations
                md["runtime_phase"] = phase
            ctx.metadata = md
            graph_dict = get_context_fabric().evolve_runtime(
                sid,
                goal_id=root,
                runtime_phase=phase,
                evidence_ref=evidence_ref,
                memory_ref=memory_ref,
            )
            md["fabric_graph_live"] = graph_dict
            from kernel.cognition.runtime_grounding import (
                attach_world_state_to_context,
                persist_world_state,
                project_from_context,
            )

            grounding = project_from_context(ctx)
            attach_world_state_to_context(ctx, grounding)
            md = getattr(ctx, "metadata", None) or {}
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    persist_world_state(str(getattr(ctx, "session_id", "") or ""), grounding)
                )
            except RuntimeError:
                pass
            try:
                from kernel.runtime.cognitive_state.bus import bind_state_to_context
                from kernel.runtime.cognitive_state.persistence import flush_runtime_state
                from kernel.runtime.cognitive_state.store import get_or_create_runtime_state

                rs = get_or_create_runtime_state(
                    str(getattr(ctx, "request_id", "") or ""),
                    str(getattr(ctx, "session_id", "") or ""),
                    goal_id=root,
                )
                rs.phase = phase or rs.phase
                rs.world_state_snapshot = dict(md.get("goal_world_projection") or {})
                bind_state_to_context(ctx, rs)
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(flush_runtime_state(rs))
                except RuntimeError:
                    pass
            except Exception as exc:
                degrade_ctx(ctx, subsystem="cognitive_state", detail="flush_runtime_state", exc=exc)
        except Exception as exc:
            degrade_ctx(ctx, subsystem="runtime_fabric_evolve", detail=phase or "unknown", exc=exc)

    def _apply_phase_governance(
        self,
        ctx: Any,
        *,
        phase: str,
        evidence_count: int = 0,
        min_evidence: int = 0,
        hallucination_risk: float = 0.0,
    ) -> None:
        ctx.metadata = ctx.metadata or {}
        policies: dict[str, Any] = dict(ctx.metadata.get("phase_policies") or {})
        try:
            if phase == "plan":
                from kernel.governance.cognitive_policy_engine import CognitivePolicyEngine

                intent = str(getattr(ctx, "task_type", "general") or "general")
                sub = len((ctx.metadata.get("goal_graph") or {}).get("goals", [])) - 1
                policies["plan"] = CognitivePolicyEngine().evaluate_planning(
                    intent_category=intent,
                    sub_goal_count=max(0, sub),
                    max_steps=int((getattr(ctx, "cognitive_budget", None) or {}).get("max_reasoning_steps", 10) or 10),
                ).__dict__
            elif phase == "evidence":
                from kernel.governance.evidence_policy_engine import EvidencePolicyEngine

                policies["evidence"] = EvidencePolicyEngine().evaluate_fusion(
                    evidence_count=evidence_count,
                    min_required=min_evidence,
                    hallucination_risk=hallucination_risk,
                ).__dict__
            elif phase == "memory":
                from kernel.governance.memory_policy_engine import MemoryPolicyEngine

                policies["memory"] = MemoryPolicyEngine().evaluate_write(
                    proposed_tokens=len(str(ctx.memory_context or "")) // 4,
                ).__dict__
            from kernel.governance.adaptive_risk_engine import AdaptiveRiskEngine

            replanned = bool(ctx.metadata.get("refine_replan"))
            ar = AdaptiveRiskEngine().score_turn(
                hallucination_risk=hallucination_risk,
                replanned=replanned,
                evidence_count=evidence_count,
                sub_goal_count=max(0, len((ctx.metadata.get("goal_graph") or {}).get("goals", [])) - 1),
            )
            ctx.metadata["adaptive_risk"] = {
                "level": ar.level,
                "score": ar.score,
                "factors": ar.factors,
            }
        except Exception as exc:
            degrade_ctx(ctx, subsystem="phase_governance", detail=phase, exc=exc)
        ctx.metadata["phase_policies"] = policies

    def _apply_execution_guardrails(
        self, ctx: Any, plan: Any, execution_graph: Any
    ) -> None:
        """执行前能力护栏检查，对计划中的子任务进行预调度约束。"""
        from kernel.governance.execution_guardrails import ExecutionGuardrails

        allowed = list(getattr(ctx, "allowed_capabilities", None) or [])
        disallowed = list(getattr(ctx, "disallowed_capabilities", None) or [])
        timeout = int(
            (getattr(ctx, "metadata", None) or {}).get("execution_timeout_sec", 30) or 30
        )
        guard = ExecutionGuardrails()
        cap_names: list[str] = []
        if execution_graph is not None:
            cap_names = [
                str(getattr(n, "capability_name", "") or getattr(n, "capability_type", ""))
                for n in execution_graph
                if getattr(n, "capability_name", None) or getattr(n, "capability_type", None)
            ]
        elif plan is not None:
            cap_names = [
                str(getattr(t, "capability_type", ""))
                for t in getattr(plan, "subtasks", [])
                if getattr(t, "capability_type", "")
            ]
        violations: list[str] = []
        from kernel.runtime.capability import capability_registry

        for cap in cap_names:
            if not cap:
                continue
            d = guard.evaluate_dispatch(
                cap,
                allowed_list=allowed or None,
                disallowed_list=disallowed or None,
                timeout_sec=timeout,
            )
            if not d.allowed:
                violations.extend(d.violations)
            violations.extend(capability_registry.validate_for_execution(cap))
        ctx.metadata = ctx.metadata or {}
        ctx.metadata["execution_guardrails"] = {
            "capabilities_checked": cap_names,
            "violations": violations,
            "allowed": len(violations) == 0,
        }

    # ── 快照辅助 ────────────────────────────────────────────────────────────

    def _capture_snapshot(
        self,
        phase: str,
        ctx: Any,
        **kwargs: Any,
    ) -> None:
        """捕获运行时快照，供回放/审计。"""
        if not settings.kernel_runtime_replay_enabled:
            return
        try:
            from kernel.runtime.replay.runtime_snapshot import runtime_snapshot_store
            runtime_snapshot_store.capture(
                phase=phase,
                request_id=getattr(ctx, "request_id", ""),
                session_id=getattr(ctx, "session_id", ""),
                **kwargs,
            )
        except Exception as exc:
            degrade_ctx(ctx, subsystem="runtime_snapshot", detail=phase, exc=exc)

    def _ensure_trace(self) -> None:
        if self._trace is None:
            from kernel.runtime.replay.deterministic_trace import DeterministicTrace
            self._trace = DeterministicTrace()

    # ── 上下文压缩 ─────────────────────────────────────────────────────────

    def compress_context(self, ctx: Any, query: str = "") -> Any:
        """应用上下文压缩以降低提示词膨胀；就地修改 ctx 中的记忆/偏好块。"""
        if not getattr(settings, "kernel_context_compressor_enabled", True):
            return ctx

        if self._context_compressor is None:
            from kernel.runtime.context_runtime.context_compressor import ContextCompressor
            self._context_compressor = ContextCompressor(max_tokens=600)

        # 压缩记忆上下文
        if ctx.memory_context and len(ctx.memory_context) > 800:
            compressed = self._context_compressor.compress(ctx.memory_context, "memory")
            if compressed.quality_score > 0.5:
                ctx.memory_context = compressed.content

        # 压缩偏好上下文
        if ctx.preference_context_block and len(ctx.preference_context_block) > 500:
            compressed = self._context_compressor.compress(ctx.preference_context_block, "preferences")
            if compressed.quality_score > 0.5:
                ctx.preference_context_block = compressed.content

        return ctx

    def _simplify_plan(self, plan: Any, decision: Any) -> Any:
        """在约束层要求简化时降低计划复杂度。"""
        if hasattr(plan, "subtasks") and len(plan.subtasks) > 1:
            # 仅保留最高优先级子任务
            plan.subtasks = [plan.subtasks[0]]
            plan.subtasks[0].depends_on = []
        return plan

    async def _direct_answer_fallback(
        self, query: str, ctx: Any
    ) -> CognitiveExecutiveResult:
        """最终降级：直接 LLM 推理回答，不使用任何外部能力。"""
        try:
            from model.model_gateway.gateway import LLMMessage, LLMRole, get_model_gateway

            gw = get_model_gateway()
            resp = await gw.complete(
                [LLMMessage(role="user", content=query)],
                role=LLMRole.QUERY,
                temperature=0.0,
                max_tokens=1024,
            )
            answer = (resp.content or "").strip()
            if answer:
                return CognitiveExecutiveResult(
                    answer=answer,
                    risk_level="low",
                    rewrite_trace="constraint_fallback_direct",
                )
        except Exception as exc:
            logger.warning("Direct answer fallback failed", error=str(exc))

        return CognitiveExecutiveResult(
            answer="抱歉，我暂时无法处理这个请求。请稍后重试或换一种方式提问。",
            risk_level="low",
            rewrite_trace="constraint_fallback_failed",
        )

    # ── 惰性初始化 ──────────────────────────────────────────────────────────

    def _ensure_rewrite_engine(self) -> None:
        if self._rewrite_engine is None:
            from kernel.runtime.rewrite_engine import RewriteEngine
            self._rewrite_engine = RewriteEngine()

    def _ensure_understanding_engine(self) -> None:
        if self._understanding_engine is None:
            from kernel.runtime.understanding_engine import UnderstandingEngine
            self._understanding_engine = UnderstandingEngine()

    def _ensure_cognitive_planner(self) -> None:
        if self._cognitive_planner is None:
            from kernel.runtime.capability import capability_registry
            from kernel.runtime.orchestrator import CognitivePlanner
            self._cognitive_planner = CognitivePlanner(capability_registry=capability_registry)

    def _ensure_cognitive_planner_v2(self) -> None:
        if self._cognitive_planner_v2 is None:
            from kernel.runtime.capability import capability_registry
            from kernel.runtime.cognitive import CognitivePlannerV2
            self._cognitive_planner_v2 = CognitivePlannerV2(capability_registry=capability_registry)

    def _ensure_strategy_builder(self) -> None:
        if self._strategy_builder is None:
            from kernel.runtime.capability import capability_registry
            from kernel.runtime.cognitive import StrategyBuilder
            self._strategy_builder = StrategyBuilder(capability_registry=capability_registry)

    def _ensure_capability_graph_builder(self) -> None:
        if self._capability_graph_builder is None:
            from kernel.runtime.capability import capability_registry
            from kernel.runtime.capability_graph_builder import CapabilityGraphBuilder
            self._capability_graph_builder = CapabilityGraphBuilder(
                capability_registry=capability_registry
            )

    def _ensure_execution_runtime(self) -> None:
        if self._execution_runtime is None:
            from kernel.runtime.capability import capability_registry
            from kernel.runtime.executor import ExecutionRuntime
            self._execution_runtime = ExecutionRuntime(
                capability_registry=capability_registry,
                timeout_sec=30,
                max_parallel=5,
            )

    def _ensure_evidence_bus(self) -> None:
        if self._evidence_bus is None:
            from kernel.runtime.evidence_bus import evidence_bus
            self._evidence_bus = evidence_bus

    def _ensure_fusion_engine(self) -> None:
        if self._fusion_engine is None:
            from kernel.runtime.fusion import FusionEngineV2
            self._fusion_engine = FusionEngineV2()

    def _ensure_critic_engine(self) -> None:
        if self._critic_engine is None:
            from kernel.runtime.critic import CriticEngineV2
            self._critic_engine = CriticEngineV2()


def _count_evidence_by_source(evidence_list: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ev in evidence_list:
        source = "unknown"
        provenance = getattr(ev, "provenance", None)
        if provenance:
            source = getattr(provenance, "source", "unknown")
        counts[source] = counts.get(source, 0) + 1
    return counts


class CognitiveExecutiveResult:
    """CognitiveExecutive.execute() 的结构化返回。

    含答案、证据、制品、计划、融合/批评结果、改写轨迹、理解与风险评估。
    """

    def __init__(
        self,
        answer: str = "",
        evidence_objects: list | None = None,
        artifact: Any = None,
        plan: Any = None,
        fusion_result: Any = None,
        critic_result: Any = None,
        rewrite_trace: str = "",
        understanding: Any = None,
        risk_level: str = "low",
        policy_denied: bool = False,
        execution_reasoning: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.answer = answer
        self.evidence_objects = evidence_objects or []
        self.artifact = artifact
        self.plan = plan
        self.fusion_result = fusion_result
        self.critic_result = critic_result
        self.rewrite_trace = rewrite_trace
        self.understanding = understanding
        self.risk_level = risk_level
        self.policy_denied = policy_denied
        self.execution_reasoning = execution_reasoning
        self.metadata: dict[str, Any] = dict(metadata or {})


def _infer_capability_from_evidence(ev) -> str | None:
    """从证据对象提取 capability_type，供反馈记录使用。"""
    # 优先 provenance.source（如 data、rag、web、tool）
    provenance = getattr(ev, "provenance", None)
    if provenance is not None:
        source = getattr(provenance, "source", "") or ""
        source_type = getattr(provenance, "source_type", "") or ""
        # Agent 类型 → 能力类型
        agent_cap_map: dict[str, str] = {
            "data": "data.query",
            "rag": "rag.retrieve",
            "web": "web.search",
            "tool": "tool.datetime",
            "skills": "skills.execute",
            "vision": "vision.analyze",
            "memory": "memory.retrieve",
        }
        if source in agent_cap_map:
            return agent_cap_map[source]
        if source_type in agent_cap_map:
            return agent_cap_map[source_type]

    # 其次 metadata.capability_type
    metadata = getattr(ev, "metadata", None)
    if isinstance(metadata, dict):
        cap_type = metadata.get("capability_type")
        if cap_type:
            return str(cap_type)

    return None
