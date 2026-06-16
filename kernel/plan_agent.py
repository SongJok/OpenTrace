"""
已弃用 — kernel/plan_agent.py

PlanAgent 与 TaskPlan/SubTask 已由 kernel.runtime.orchestrator.UnifiedOrchestrator（Phase 2）取代。
TaskPlan/SubTask 数据类仅为向后兼容保留。

新代码应使用 UnifiedOrchestrator.plan()，勿再调用 PlanAgent.generate_plan()。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from execution.data.query_intents import is_database_question
from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)
from kernel.adaptive_profiles import get_profile_defaults
from kernel.cognition.world_model import WorldModel
from kernel.plan_memory import PlanMemoryRecord, plan_memory
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway


@dataclass
class SubTask:
    agent_type: Literal["data", "tool", "web", "memory", "rag", "rule_engine", "vision"]
    query: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    priority: Literal["high", "normal", "low"] = "normal"
    sub_question_id: str = ""
    display_order: int = 0


@dataclass
class TaskPlan:
    subtasks: list[SubTask] = field(default_factory=list)
    merge_strategy: Literal["union", "compare", "prioritized"] = "prioritized"
    max_parallel: int = 3
    adaptive_profile: dict[str, Any] = field(default_factory=dict)
    is_multi_question: bool = False


class PlanAgent:
    def __init__(self) -> None:
        self.world_model = WorldModel()

    def _guess_query_type(self, user_query: str) -> str:
        q = (user_query or "").lower()
        if is_database_question(user_query) or any(k in q for k in ["报表", "销量", "订单"]):
            return "data"
        if any(k in q for k in ["文档", "手册", "知识库", "总结", "归纳", "pdf", "docx", "从文档"]):
            return "rag"
        if any(k in q for k in ["天气", "气温", "温度", "下雨", "预报", "weather", "forecast"]):
            return "tool"
        if any(k in q for k in ["最新", "新闻", "实时", "联网", "搜索"]):
            return "web"
        if any(k in q for k in ["几点", "现在几点", "当前时间", "what time"]):
            return "tool"
        return "general"

    def _ground_query_terms(self, user_query: str) -> list[dict[str, Any]]:
        terms = []
        for token in ["华东", "华东区", "上季度", "上一季度", "east china", "q-1"]:
            if token.lower() in (user_query or "").lower():
                g = self.world_model.ground(token)
                terms.append(
                    {
                        "term": token,
                        "canonical_name": g.canonical_name,
                        "entity_type": g.entity_type,
                        "confidence": g.confidence,
                        "mappings": g.mappings,
                    }
                )
        return terms

    async def generate_plan(
        self, user_query: str, context: dict[str, Any] | None = None
    ) -> TaskPlan:
        adaptive_profile = (
            (context or {}).get("adaptive_profile") if isinstance(context, dict) else {}
        )
        if not isinstance(adaptive_profile, dict):
            adaptive_profile = {}
        prompt = (
            "你是任务规划专家。把用户问题拆成可并行子任务，输出 JSON。"
            "可用 agent_type 与职责："
            "data(结构化数据查询), web(联网检索), rag(内部文档+记忆检索), tool(工具执行), memory(长期记忆检索)。"
            "若涉及数据库分析，必须包含 data 子任务；且必须在 data.params 中传入 data_source_id（从 context.metadata.data_source_id 获取）。"
            "若 context.metadata.data_source_id 为空，则不要生成 data 子任务。"
            "若问题需要参考内部文档、历史知识、用户偏好，优先加入 rag 子任务。"
            "rag 可在 params 指定 top_k 和 sources，默认 top_k=8, sources=[documents, semantic_memory]。"
            "若用户一次提多个目标（如 查询+图表+分析），可同时返回 data + tool 子任务并行执行。"
        )
        # 如有可用，注入澄清上下文（特性⑤）
        metadata = (context or {}).get("metadata", {}) if isinstance(context, dict) else {}
        clarify_context = (
            ((context or {}).get("clarify_context") if isinstance(context, dict) else None)
            or metadata.get("clarify_context")
            if isinstance(metadata, dict)
            else None
        )
        if clarify_context and isinstance(clarify_context, str) and clarify_context.strip():
            clarify_part = (
                f"\n用户基于上一轮的追问补充了以下信息：{clarify_context.strip()}\n"
                "请结合补充信息重新规划，优先使用明确的数据源、表名或查询目标。"
            )
            prompt += clarify_part

        # 如有可用，注入对话状态（特性②）
        dialogue_state = (
            (context or {}).get("dialogue_state") if isinstance(context, dict) else None
        )
        if (
            dialogue_state
            and isinstance(dialogue_state, dict)
            and dialogue_state.get("referenced_previous_result")
        ):
            dst_part = (
                f"\n对话状态追踪结果：\n"
                f"- 当前话题域：{dialogue_state.get('active_domain', 'general_qa')}\n"
                f"- 引用了上轮结果：是（agent类型={dialogue_state.get('referenced_agent_type', 'unknown')}）\n"
                f"- 消解后的完整查询：{dialogue_state.get('resolved_query', user_query)}\n"
                "请优先沿用上一轮使用的 agent 类型和数据源参数，仅更新查询内容。"
            )
            prompt += dst_part
            # 使用消解后的查询作为有效查询
            resolved = dialogue_state.get("resolved_query", "")
            if resolved and resolved != user_query:
                user_query = resolved

        # ── 多轮：注入对话历史 ──
        conversation_history = (
            (context or {}).get("conversation_history") if isinstance(context, dict) else None
        )
        if (
            conversation_history
            and isinstance(conversation_history, list)
            and len(conversation_history) > 0
        ):
            recent = conversation_history[-6:]
            history_text = "\n".join(
                f"[{h.get('role', '?')}]: {str(h.get('content', ''))[:200]}" for h in recent
            )
            prompt += (
                f"\n最近的对话历史（用于理解上下文和用户意图）：\n{history_text}\n"
                "规则：如果用户是在追问、细化或延续上文，请优先复用上文中提到的数据源和 Agent 类型。"
                "如果用户切换了话题，请按新话题规划。"
            )

        # ── 多轮：注入 ConversationState 上下文 ──
        conv_state = (
            (context or {}).get("conversation_state") if isinstance(context, dict) else None
        )
        if conv_state and isinstance(conv_state, dict):
            cs_parts = []
            if conv_state.get("active_topic"):
                cs_parts.append(f"- 当前话题：{conv_state['active_topic']}")
            if conv_state.get("active_intent"):
                cs_parts.append(f"- 当前意图：{conv_state['active_intent']}")
            if conv_state.get("active_data_source_id"):
                cs_parts.append(f"- 活跃数据源：{conv_state['active_data_source_id']}")
            last_plan = conv_state.get("last_plan")
            if isinstance(last_plan, dict) and last_plan.get("subtasks"):
                prev_agents = [
                    s.get("agent_type", "?") for s in last_plan["subtasks"] if isinstance(s, dict)
                ]
                if prev_agents:
                    cs_parts.append(f"- 上一轮使用的 Agent：{', '.join(prev_agents)}")
            if cs_parts:
                prompt += (
                    "\n当前会话状态：\n" + "\n".join(cs_parts) + "\n"
                    "如果用户是在延续当前话题，优先沿用上轮的 Agent 和参数配置。"
                )

        # ── Intent Lock: 注入能力约束 ──
        metadata = (context or {}).get("metadata", {}) if isinstance(context, dict) else {}
        if not isinstance(metadata, dict):
            metadata = {}
        intent_lock = metadata.get("intent_lock", {}) if isinstance(metadata, dict) else {}
        if isinstance(intent_lock, dict) and intent_lock.get("task_type"):
            task_type = intent_lock.get("task_type", "general_qa")
            allowed = intent_lock.get("allowed_capabilities", [])
            disallowed = intent_lock.get("disallowed_capabilities", [])
            il_parts: list[str] = [
                f"\n## 意图约束 (Intent Lock)\n当前任务类型: {task_type}"
            ]
            if allowed:
                il_parts.append(f"仅允许使用的能力: {', '.join(allowed)}")
                if "model.answer" in allowed and len(allowed) == 1:
                    il_parts.append(
                        "**关键**: 仅允许 'model.answer'，意味着你只能用 LLM 直接回答。"
                        "不要生成任何 data/web/rag/tool 子任务。subtasks 必须为空数组 []。"
                    )
            if disallowed:
                il_parts.append(f"严格禁止使用的能力: {', '.join(disallowed)}")
                il_parts.append(
                    "禁止的能力对应的 agent_type: "
                    "rag.retrieve→rag, web.search→web, data.query→data, "
                    "tool.weather→tool, tool.datetime→tool. "
                    "严禁为禁止的能力生成对应的 agent 子任务。"
                )
            prompt += "\n".join(il_parts) + "\n"

        recent_patterns: list[dict[str, Any]] = []
        if bool(getattr(settings, "kernel_plan_memory_enabled", True)):
            intent_hint = self._guess_query_type(user_query)
            recent_patterns = [
                {
                    "query_type": r.query_type,
                    "subtasks": r.subtasks,
                    "score": r.score,
                }
                for r in plan_memory.recent_successful_plans(intent_hint, limit=3)
            ]

        grounded_terms = self._ground_query_terms(user_query)
        merged_context = dict(context or {})
        if grounded_terms:
            merged_context["grounded_terms"] = grounded_terms
        if recent_patterns:
            merged_context["recent_success_patterns"] = recent_patterns

        user = f"query={user_query}\ncontext={json.dumps(merged_context, ensure_ascii=False)}"
        gw = get_model_gateway()
        resp = await gw.complete(
            [LLMMessage(role="system", content=prompt), LLMMessage(role="user", content=user)],
            role=LLMRole.PLANNING,
            temperature=0.0,
            max_tokens=400,
        )
        text = (resp.content or "").strip()

        q = user_query.lower()
        md = (context or {}).get("metadata") if isinstance(context, dict) else {}
        if not isinstance(md, dict):
            md = {}
        selected_data_source_id = str(md.get("data_source_id", "") or "").strip()

        def _ensure_rules(sts: list[SubTask]) -> tuple[list[SubTask], int]:
            has = {s.agent_type for s in sts}
            profile_name = str(adaptive_profile.get("name", "balanced") or "balanced")
            profile_defaults = get_profile_defaults(profile_name)
            min_agents = (
                1
                if profile_name == "speed"
                else 2 if profile_name in {"quality", "identity"} else 1
            )
            desired_max_parallel = int(
                adaptive_profile.get("max_parallel", profile_defaults.get("max_parallel", 3))
                or profile_defaults.get("max_parallel", 3)
            )

            for s in sts:
                if s.agent_type == "data":
                    p = dict(s.params or {})
                    if selected_data_source_id and not str(p.get("data_source_id", "")).strip():
                        p["data_source_id"] = selected_data_source_id
                    s.params = p

            doc_intent = any(
                k in q
                for k in [
                    "文档",
                    "手册",
                    "知识库",
                    "根据文档",
                    "从文档",
                    "政策",
                    "规范",
                    "记忆",
                    "读取",
                    "读一下",
                    "总结",
                    "归纳",
                    "提炼",
                    "上传文档",
                    "附件",
                    ".pdf",
                    ".doc",
                    ".docx",
                    ".txt",
                    ".md",
                    "pdf",
                    "docx",
                ]
            )
            web_intent = any(
                k in q
                for k in ["新闻", "实时", "最新", "今天", "联网", "搜索", "天气", "气温", "降雨"]
            )
            data_intent = is_database_question(user_query) or any(
                k in q for k in ["分布", "订单", "用户", "销量", "饼图", "柱状图"]
            )
            tool_intent = any(
                k in q
                for k in [
                    "时间",
                    "几点",
                    "计算",
                    "图表",
                    "代码",
                    "执行",
                    "sql",
                    "查询",
                    "tool",
                    "天气",
                    "分析",
                ]
            )

            if doc_intent and "rag" not in has:
                sts.append(
                    SubTask(
                        agent_type="rag",
                        query=user_query,
                        params={
                            "top_k": 8,
                            "sources": ["documents", "semantic_memory"],
                            "min_evidence_score": float(
                                getattr(settings, "rag_min_evidence_score", 0.65)
                            ),
                            "fallback_to_web": bool(
                                getattr(settings, "rag_auto_fallback_to_web", True)
                            ),
                        },
                        priority="high",
                    )
                )
                has.add("rag")
            if web_intent and "web" not in has:
                sts.append(SubTask(agent_type="web", query=user_query))
                has.add("web")
            if data_intent and selected_data_source_id and "data" not in has:
                sts.append(
                    SubTask(
                        agent_type="data",
                        query=user_query,
                        params={"data_source_id": selected_data_source_id},
                    )
                )
                has.add("data")
            if data_intent and selected_data_source_id and "data" in has:
                for s in sts:
                    if s.agent_type == "data":
                        p = dict(s.params or {})
                        p.setdefault("data_source_id", selected_data_source_id)
                        s.params = p
            if tool_intent and "tool" not in has:
                sts.append(SubTask(agent_type="tool", query=user_query))
                has.add("tool")

            if profile_name == "quality":
                if data_intent and selected_data_source_id and "rag" not in has:
                    sts.append(
                        SubTask(
                            agent_type="rag",
                            query=user_query,
                            params={
                                "top_k": 8,
                                "sources": ["documents", "semantic_memory"],
                                "min_evidence_score": 0.65,
                                "fallback_to_web": True,
                            },
                            priority="high",
                        )
                    )
                    has.add("rag")
                if web_intent and "web" not in has:
                    sts.append(SubTask(agent_type="web", query=user_query))
                    has.add("web")
            elif profile_name == "speed":
                sts = sts[: max(1, min(2, len(sts)))]
                if not sts:
                    sts = [SubTask(agent_type="tool", query=user_query)]

            if len(sts) < min_agents:
                if doc_intent and "rag" not in has:
                    sts.append(
                        SubTask(
                            agent_type="rag",
                            query=user_query,
                            params={"top_k": 8, "sources": ["documents", "semantic_memory"]},
                        )
                    )
                elif web_intent and "web" not in has:
                    sts.append(SubTask(agent_type="web", query=user_query, priority="normal"))
                elif data_intent and selected_data_source_id and "data" not in has:
                    sts.append(
                        SubTask(
                            agent_type="data",
                            query=user_query,
                            params={"data_source_id": selected_data_source_id},
                        )
                    )

            return sts, desired_max_parallel

        try:
            s = text[text.find("{") : text.rfind("}") + 1]
            data = json.loads(s)
            subtasks = [SubTask(**x) for x in data.get("subtasks", []) if isinstance(x, dict)]
            merge_strategy = data.get("merge_strategy", "prioritized")
            max_parallel = int(data.get("max_parallel", 3))
            subtasks, max_parallel = _ensure_rules(subtasks)
            # ── Intent Lock: 过滤被禁能力的 subtask ──
            subtasks = self._filter_disallowed_subtasks(subtasks, intent_lock)
            if not subtasks:
                raise ValueError("empty subtasks")
            plan = TaskPlan(
                subtasks=subtasks,
                merge_strategy=merge_strategy,
                max_parallel=max_parallel,
                adaptive_profile=get_profile_defaults(
                    str(adaptive_profile.get("name", "balanced") or "balanced")
                ),
            )
        except Exception:
            subtasks: list[SubTask] = []
            if any(k in q for k in ["行业", "新闻", "搜索", "web", "联网"]):
                subtasks.append(SubTask(agent_type="web", query=user_query))
            if any(
                k in q
                for k in [
                    "文档",
                    "手册",
                    "知识库",
                    "历史记录",
                    "记忆",
                    "政策",
                    "规范",
                    "读取",
                    "总结",
                    "归纳",
                    ".pdf",
                    ".doc",
                    ".docx",
                    ".txt",
                    "pdf",
                    "docx",
                ]
            ):
                subtasks.append(
                    SubTask(
                        agent_type="rag",
                        query=user_query,
                        params={
                            "top_k": 8,
                            "sources": ["documents", "semantic_memory"],
                            "min_evidence_score": float(
                                getattr(settings, "rag_min_evidence_score", 0.65)
                            ),
                            "fallback_to_web": bool(
                                getattr(settings, "rag_auto_fallback_to_web", True)
                            ),
                        },
                        priority="high",
                    )
                )
            if any(
                k in q
                for k in [
                    "时间",
                    "几点",
                    "天气",
                    "计算",
                    "图表",
                    "代码",
                    "执行",
                    "sql",
                    "查询",
                    "tool",
                ]
            ):
                subtasks.append(SubTask(agent_type="tool", query=user_query))
            subtasks, max_parallel = _ensure_rules(subtasks)
            # ── Intent Lock: 过滤被禁能力的 subtask ──
            subtasks = self._filter_disallowed_subtasks(subtasks, intent_lock)
            plan = TaskPlan(
                subtasks=subtasks,
                merge_strategy="prioritized",
                max_parallel=max_parallel,
                adaptive_profile=get_profile_defaults(
                    str(adaptive_profile.get("name", "balanced") or "balanced")
                ),
            )

        def _attach_dependencies(sts: list[SubTask]) -> list[SubTask]:
            if not sts:
                return sts
            data_nodes = []
            web_nodes = []
            for idx, s in enumerate(sts):
                node_id = f"node_{idx}_{s.agent_type}"
                if s.agent_type == "data":
                    data_nodes.append(node_id)
                elif s.agent_type == "web":
                    web_nodes.append(node_id)
            for idx, s in enumerate(sts):
                node_id = f"node_{idx}_{s.agent_type}"
                deps: list[str] = []
                if s.agent_type == "rag":
                    deps.extend(data_nodes or web_nodes)
                elif s.agent_type == "tool" and (data_nodes or web_nodes):
                    deps.extend((data_nodes + web_nodes)[:2])
                elif s.agent_type == "web" and data_nodes:
                    deps.extend(data_nodes)
                if deps:
                    s.depends_on = list(dict.fromkeys(deps))
            return sts

        plan.subtasks = _attach_dependencies(plan.subtasks)

        if bool(getattr(settings, "kernel_plan_memory_enabled", True)):
            try:
                plan_memory.add(
                    PlanMemoryRecord(
                        intent=self._guess_query_type(user_query),
                        query_type=self._guess_query_type(user_query),
                        subtasks=[s.agent_type for s in plan.subtasks],
                        score=0.8 if plan.subtasks else 0.1,
                        metadata={"profile": plan.adaptive_profile},
                    )
                )
            except Exception:
                pass
        return plan

    _DOMAIN_AGENT_MAP = {
        "data_query": "data",
        "document_retrieval": "rag",
        "web_search": "web",
        "tool_execution": "tool",
        "general_qa": "tool",
    }

    # intent_lock capability → PlanAgent agent_type 映射（用于过滤被禁子任务）
    _CAP_AGENT_MAP: dict[str, str] = {
        "rag.retrieve": "rag",
        "web.search": "web",
        "data.query": "data",
        "memory.retrieve": "memory",
        "tool.weather": "tool",
        "tool.datetime": "tool",
        "tool.execute": "tool",
        "skills.execute": "skills",
        "vision.analyze": "vision",
    }

    def _filter_disallowed_subtasks(
        self, subtasks: list[Any], intent_lock: dict[str, Any] | None
    ) -> list[Any]:
        """根据 Intent Lock 的禁止能力列表过滤子任务。"""
        if not isinstance(intent_lock, dict) or not subtasks:
            return subtasks
        disallowed = intent_lock.get("disallowed_capabilities", [])
        if not disallowed:
            return subtasks
        disallowed_agents = {
            self._CAP_AGENT_MAP.get(c, c) for c in disallowed
        }
        filtered = [s for s in subtasks if getattr(s, "agent_type", "") not in disallowed_agents]
        if len(filtered) < len(subtasks):
            logger.info(
                "PlanAgent filtered disallowed subtasks",
                original=len(subtasks),
                filtered=len(filtered),
                removed_agents=[getattr(s, "agent_type", "?") for s in subtasks if s not in filtered],
            )
        return filtered

    def _build_params_for_agent(
        self, agent_type: str, sq: dict[str, str], selected_data_source_id: str
    ) -> dict[str, Any]:
        """为每种 Agent 类型构建合理的默认参数。"""
        params: dict[str, Any] = {}
        if agent_type == "data" and selected_data_source_id:
            params["data_source_id"] = selected_data_source_id
        elif agent_type == "rag":
            params.update(
                {
                    "top_k": 8,
                    "sources": ["documents", "semantic_memory"],
                    "min_evidence_score": 0.65,
                    "fallback_to_web": True,
                }
            )
        elif agent_type == "web":
            params["fallback_to_web"] = True
        return params

    async def generate_multi_plan(
        self, sub_questions: list[dict[str, str]], context: dict[str, Any] | None = None
    ) -> TaskPlan:
        """生成多问题 TaskPlan，子任务按顺序排列。"""
        adaptive_profile = (
            (context or {}).get("adaptive_profile") if isinstance(context, dict) else {}
        )
        if not isinstance(adaptive_profile, dict):
            adaptive_profile = {}

        selected_data_source_id = ""
        has_rag = bool(settings.kernel_agent_rag_enabled)
        has_web = True
        if isinstance(context, dict):
            md = context.get("metadata") if isinstance(context, dict) else {}
            if isinstance(md, dict):
                selected_data_source_id = str(md.get("data_source_id", "") or "").strip()

        # 为 LLM 构建领域上下文
        domain_summary = "\n".join(
            f"  q{i+1}[{sq.get('domain', 'general_qa')}]: {sq.get('text', '')}"
            for i, sq in enumerate(sub_questions)
        )
        context_hints = []
        if selected_data_source_id:
            context_hints.append(
                f"- 已配置数据源(data_source_id={selected_data_source_id})，data_query 类问题应使用 data agent"
            )
        else:
            context_hints.append("- 未配置数据源，data_query 类问题应降级为 tool agent")
        if not has_rag:
            context_hints.append(
                "- RAG agent 当前不可用，document_retrieval 类问题应降级为 tool agent"
            )

        # ── 多轮：注入对话历史 ──
        conversation_history = (
            (context or {}).get("conversation_history") if isinstance(context, dict) else None
        )
        history_hint = ""
        if (
            conversation_history
            and isinstance(conversation_history, list)
            and len(conversation_history) > 0
        ):
            recent = conversation_history[-6:]
            history_text = "\n".join(
                f"[{h.get('role', '?')}]: {str(h.get('content', ''))[:200]}" for h in recent
            )
            history_hint = (
                f"\n最近的对话历史：\n{history_text}\n"
                "如果子问题与历史对话相关，请优先复用历史中的数据源和 Agent 参数。\n"
            )

        # ── 多轮：注入 ConversationState 上下文 ──
        conv_state = (
            (context or {}).get("conversation_state") if isinstance(context, dict) else None
        )
        conv_state_hint = ""
        if conv_state and isinstance(conv_state, dict):
            cs_parts = []
            if conv_state.get("active_topic"):
                cs_parts.append(f"- 当前话题：{conv_state['active_topic']}")
            if conv_state.get("active_data_source_id"):
                cs_parts.append(f"- 活跃数据源：{conv_state['active_data_source_id']}")
            last_plan = conv_state.get("last_plan")
            if isinstance(last_plan, dict) and last_plan.get("subtasks"):
                prev_agents = [
                    s.get("agent_type", "?") for s in last_plan["subtasks"] if isinstance(s, dict)
                ]
                if prev_agents:
                    cs_parts.append(f"- 上一轮使用的 Agent：{', '.join(prev_agents)}")
            if cs_parts:
                conv_state_hint = (
                    "\n当前会话状态：\n" + "\n".join(cs_parts) + "\n"
                    "如果子问题是在延续当前话题，优先沿用上轮的 Agent 和参数配置。\n"
                )

        prompt = (
            "你是任务规划专家。用户提出了多个子问题，为每个子问题分配合适的 agent_type 和查询文本。\n"
            "可用 agent_type：data(数据库/结构化查询), rag(文档/知识库检索), web(联网搜索), tool(通用工具/问答)。\n"
            "规则：\n"
            "- 根据每个子问题的 domain 选择 agent_type\n"
            f"{chr(10).join(context_hints) if context_hints else ''}\n"
            "- query 字段可以改写原问题使其更精准，也可以保持原样\n"
            '- 如果 rag agent 可用，为文档检索类问题添加 params: {"top_k": 8, "sources": ["documents", "semantic_memory"]}\n'
            '- 如果 data agent 可用且有数据源，为数据查询类问题添加 params: {"data_source_id": "..."}\n'
            '- 输出 JSON：{"subtasks": [{"agent_type": "rag", "query": "...", "params": {}}]}\n'
            f"{history_hint}"
            f"{conv_state_hint}"
            f"子问题列表（含 domain）：\n{domain_summary}"
        )

        subtasks: list[SubTask] = []
        try:
            gw = get_model_gateway()
            resp = await gw.complete(
                [
                    LLMMessage(role="system", content=prompt),
                    LLMMessage(role="user", content=json.dumps(sub_questions, ensure_ascii=False)),
                ],
                role=LLMRole.PLANNING,
                temperature=0.0,
                max_tokens=500,
            )
            text = (resp.content or "").strip()
            s = text[text.find("{") : text.rfind("}") + 1]
            data = json.loads(s)
            for i, st_data in enumerate(data.get("subtasks", [])):
                if not isinstance(st_data, dict):
                    continue
                sq = sub_questions[i] if i < len(sub_questions) else None
                agent_type = st_data.get("agent_type", "tool")
                st_params = dict(st_data.get("params", {}))
                if not st_params:
                    st_params = self._build_params_for_agent(
                        agent_type, sq or {}, selected_data_source_id
                    )
                subtasks.append(
                    SubTask(
                        agent_type=agent_type,
                        query=st_data.get("query", sq.get("text", "") if sq else ""),
                        params=st_params,
                        sub_question_id=sq.get("id", f"q{i+1}") if sq else f"q{i+1}",
                        display_order=i + 1,
                        priority="high" if i == 0 else "normal",
                    )
                )
        except Exception:
            # 启发式降级：按领域分配类型
            for i, sq in enumerate(sub_questions):
                domain = sq.get("domain", "general_qa")
                agent_type = self._DOMAIN_AGENT_MAP.get(domain, "tool")
                # 无数据源时降级 data→tool
                if agent_type == "data" and not selected_data_source_id:
                    agent_type = "tool"
                if agent_type == "rag" and not has_rag:
                    agent_type = "tool"
                subtasks.append(
                    SubTask(
                        agent_type=agent_type,
                        query=sq.get("text", ""),
                        params=self._build_params_for_agent(
                            agent_type, sq, selected_data_source_id
                        ),
                        sub_question_id=sq.get("id", f"q{i+1}"),
                        display_order=i + 1,
                        priority="high" if i == 0 else "normal",
                    )
                )

        # ── Intent Lock: 过滤被禁能力的 subtask ──
        md = (context or {}).get("metadata", {}) if isinstance(context, dict) else {}
        if not isinstance(md, dict):
            md = {}
        intent_lock = md.get("intent_lock", {}) if isinstance(md, dict) else {}
        subtasks = self._filter_disallowed_subtasks(subtasks, intent_lock)

        if not subtasks:
            return TaskPlan(subtasks=[], merge_strategy="prioritized", is_multi_question=True)

        self.__attach_deps_multi(subtasks, sub_questions)

        return TaskPlan(
            subtasks=subtasks,
            merge_strategy="prioritized",
            max_parallel=min(5, len(subtasks)),
            adaptive_profile=get_profile_defaults(
                str(adaptive_profile.get("name", "balanced") or "balanced")
            ),
            is_multi_question=True,
        )

    def __attach_deps_multi(self, sts: list[SubTask], sub_questions: list[dict[str, str]]) -> None:
        """为跨问题依赖建立关联。"""
        if not sts or len(sub_questions) < 2:
            return
        sq_to_st: dict[str, SubTask] = {}
        for s in sts:
            if s.sub_question_id:
                sq_to_st[s.sub_question_id] = s

        # 表示依赖前文结果的引用词
        _DEP_REFERENCES = [
            "它们",
            "这些",
            "上述",
            "其",
            "该产品",
            "该结果",
            "基于以上",
            "根据以上",
            "根据上述",
            "在此基础上",
            "based on the above",
            "based on that",
            "these",
            "its",
            "their",
            "the above",
            "those results",
        ]

        for sq in sub_questions:
            text = sq.get("text", "")
            if any(ref in text.lower() for ref in _DEP_REFERENCES):
                idx = sub_questions.index(sq)
                if idx > 0:
                    prev_sq = sub_questions[idx - 1]
                    prev_st = sq_to_st.get(prev_sq.get("id", ""))
                    current_st = sq_to_st.get(sq.get("id", ""))
                    if prev_st and current_st:
                        node_id = f"node_{sts.index(prev_st)}_{prev_st.agent_type}"
                        if node_id not in current_st.depends_on:
                            current_st.depends_on.append(node_id)
