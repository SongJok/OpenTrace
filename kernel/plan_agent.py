from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from execution.data.query_intents import is_database_question
from infra.config.settings import settings
from kernel.adaptive_profiles import get_profile_defaults
from kernel.cognition.world_model import WorldModel
from kernel.plan_memory import PlanMemoryRecord, plan_memory
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway


@dataclass
class SubTask:
    agent_type: Literal["data", "tool", "web", "memory", "rag", "rule_engine"]
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
        if any(k in q for k in ["最新", "新闻", "实时", "今天", "联网", "搜索", "天气"]):
            return "web"
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

    async def generate_plan(self, user_query: str, context: dict[str, Any] | None = None) -> TaskPlan:
        adaptive_profile = (context or {}).get("adaptive_profile") if isinstance(context, dict) else {}
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
            min_agents = 1 if profile_name == "speed" else 2 if profile_name in {"quality", "identity"} else 1
            desired_max_parallel = int(adaptive_profile.get("max_parallel", profile_defaults.get("max_parallel", 3)) or profile_defaults.get("max_parallel", 3))

            for s in sts:
                if s.agent_type == "data":
                    p = dict(s.params or {})
                    if selected_data_source_id and not str(p.get("data_source_id", "")).strip():
                        p["data_source_id"] = selected_data_source_id
                    s.params = p

            doc_intent = any(k in q for k in ["文档", "手册", "知识库", "根据文档", "从文档", "政策", "规范", "记忆", "读取", "读一下", "总结", "归纳", "提炼", "上传文档", "附件", ".pdf", ".doc", ".docx", ".txt", ".md", "pdf", "docx"])
            web_intent = any(k in q for k in ["新闻", "实时", "最新", "今天", "联网", "搜索", "天气", "气温", "降雨"])
            data_intent = is_database_question(user_query) or any(k in q for k in ["分布", "订单", "用户", "销量", "饼图", "柱状图"])
            tool_intent = any(k in q for k in ["时间", "几点", "计算", "图表", "代码", "执行", "sql", "查询", "tool", "天气", "分析"])

            if doc_intent and "rag" not in has:
                sts.append(
                    SubTask(
                        agent_type="rag",
                        query=user_query,
                        params={
                            "top_k": 8,
                            "sources": ["documents", "semantic_memory"],
                            "min_evidence_score": float(getattr(settings, "rag_min_evidence_score", 0.65)),
                            "fallback_to_web": bool(getattr(settings, "rag_auto_fallback_to_web", True)),
                        },
                        priority="high",
                    )
                )
                has.add("rag")
            if web_intent and "web" not in has:
                sts.append(SubTask(agent_type="web", query=user_query))
                has.add("web")
            if data_intent and selected_data_source_id and "data" not in has:
                sts.append(SubTask(agent_type="data", query=user_query, params={"data_source_id": selected_data_source_id}))
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
                            params={"top_k": 8, "sources": ["documents", "semantic_memory"], "min_evidence_score": 0.65, "fallback_to_web": True},
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
                    sts.append(SubTask(agent_type="rag", query=user_query, params={"top_k": 8, "sources": ["documents", "semantic_memory"]}))
                elif web_intent and "web" not in has:
                    sts.append(SubTask(agent_type="web", query=user_query, priority="normal"))
                elif data_intent and selected_data_source_id and "data" not in has:
                    sts.append(SubTask(agent_type="data", query=user_query, params={"data_source_id": selected_data_source_id}))

            return sts, desired_max_parallel

        try:
            s = text[text.find("{") : text.rfind("}") + 1]
            data = json.loads(s)
            subtasks = [SubTask(**x) for x in data.get("subtasks", []) if isinstance(x, dict)]
            merge_strategy = data.get("merge_strategy", "prioritized")
            max_parallel = int(data.get("max_parallel", 3))
            subtasks, max_parallel = _ensure_rules(subtasks)
            if not subtasks:
                raise ValueError("empty subtasks")
            plan = TaskPlan(subtasks=subtasks, merge_strategy=merge_strategy, max_parallel=max_parallel, adaptive_profile=get_profile_defaults(str(adaptive_profile.get("name", "balanced") or "balanced")))
        except Exception:
            subtasks: list[SubTask] = []
            if any(k in q for k in ["行业", "新闻", "搜索", "web", "联网"]):
                subtasks.append(SubTask(agent_type="web", query=user_query))
            if any(k in q for k in ["文档", "手册", "知识库", "历史记录", "记忆", "政策", "规范", "读取", "总结", "归纳", ".pdf", ".doc", ".docx", ".txt", "pdf", "docx"]):
                subtasks.append(
                    SubTask(
                        agent_type="rag",
                        query=user_query,
                        params={
                            "top_k": 8,
                            "sources": ["documents", "semantic_memory"],
                            "min_evidence_score": float(getattr(settings, "rag_min_evidence_score", 0.65)),
                            "fallback_to_web": bool(getattr(settings, "rag_auto_fallback_to_web", True)),
                        },
                        priority="high",
                    )
                )
            if any(k in q for k in ["时间", "几点", "天气", "计算", "图表", "代码", "执行", "sql", "查询", "tool"]):
                subtasks.append(SubTask(agent_type="tool", query=user_query))
            subtasks, max_parallel = _ensure_rules(subtasks)
            plan = TaskPlan(subtasks=subtasks, merge_strategy="prioritized", max_parallel=max_parallel, adaptive_profile=get_profile_defaults(str(adaptive_profile.get("name", "balanced") or "balanced")))

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

    def _build_params_for_agent(
        self, agent_type: str, sq: dict[str, str], selected_data_source_id: str
    ) -> dict[str, Any]:
        """Build sensible default params per agent type."""
        params: dict[str, Any] = {}
        if agent_type == "data" and selected_data_source_id:
            params["data_source_id"] = selected_data_source_id
        elif agent_type == "rag":
            params.update({
                "top_k": 8,
                "sources": ["documents", "semantic_memory"],
                "min_evidence_score": 0.65,
                "fallback_to_web": True,
            })
        elif agent_type == "web":
            params["fallback_to_web"] = True
        return params

    async def generate_multi_plan(
        self, sub_questions: list[dict[str, str]], context: dict[str, Any] | None = None
    ) -> TaskPlan:
        """Generate a multi-question TaskPlan with ordered subtasks."""
        adaptive_profile = (context or {}).get("adaptive_profile") if isinstance(context, dict) else {}
        if not isinstance(adaptive_profile, dict):
            adaptive_profile = {}

        selected_data_source_id = ""
        has_rag = bool(settings.kernel_agent_rag_enabled)
        has_web = True
        if isinstance(context, dict):
            md = context.get("metadata") if isinstance(context, dict) else {}
            if isinstance(md, dict):
                selected_data_source_id = str(md.get("data_source_id", "") or "").strip()

        # Build domain context for the LLM
        domain_summary = "\n".join(
            f"  q{i+1}[{sq.get('domain', 'general_qa')}]: {sq.get('text', '')}"
            for i, sq in enumerate(sub_questions)
        )
        context_hints = []
        if selected_data_source_id:
            context_hints.append(f"- 已配置数据源(data_source_id={selected_data_source_id})，data_query 类问题应使用 data agent")
        else:
            context_hints.append("- 未配置数据源，data_query 类问题应降级为 tool agent")
        if not has_rag:
            context_hints.append("- RAG agent 当前不可用，document_retrieval 类问题应降级为 tool agent")

        prompt = (
            "你是任务规划专家。用户提出了多个子问题，为每个子问题分配合适的 agent_type 和查询文本。\n"
            "可用 agent_type：data(数据库/结构化查询), rag(文档/知识库检索), web(联网搜索), tool(通用工具/问答)。\n"
            "规则：\n"
            "- 根据每个子问题的 domain 选择 agent_type\n"
            f"{chr(10).join(context_hints) if context_hints else ''}\n"
            "- query 字段可以改写原问题使其更精准，也可以保持原样\n"
            "- 如果 rag agent 可用，为文档检索类问题添加 params: {\"top_k\": 8, \"sources\": [\"documents\", \"semantic_memory\"]}\n"
            "- 如果 data agent 可用且有数据源，为数据查询类问题添加 params: {\"data_source_id\": \"...\"}\n"
            '- 输出 JSON：{"subtasks": [{"agent_type": "rag", "query": "...", "params": {}}]}\n'
            f"子问题列表（含 domain）：\n{domain_summary}"
        )

        subtasks: list[SubTask] = []
        try:
            gw = get_model_gateway()
            resp = await gw.complete(
                [LLMMessage(role="system", content=prompt),
                 LLMMessage(role="user", content=json.dumps(sub_questions, ensure_ascii=False))],
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
                    st_params = self._build_params_for_agent(agent_type, sq or {}, selected_data_source_id)
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
            # Heuristic fallback: assign types based on domain
            for i, sq in enumerate(sub_questions):
                domain = sq.get("domain", "general_qa")
                agent_type = self._DOMAIN_AGENT_MAP.get(domain, "tool")
                # Downgrade data→tool if no data source
                if agent_type == "data" and not selected_data_source_id:
                    agent_type = "tool"
                if agent_type == "rag" and not has_rag:
                    agent_type = "tool"
                subtasks.append(
                    SubTask(
                        agent_type=agent_type,
                        query=sq.get("text", ""),
                        params=self._build_params_for_agent(agent_type, sq, selected_data_source_id),
                        sub_question_id=sq.get("id", f"q{i+1}"),
                        display_order=i + 1,
                        priority="high" if i == 0 else "normal",
                    )
                )

        if not subtasks:
            return TaskPlan(subtasks=[], merge_strategy="prioritized", is_multi_question=True)

        self.__attach_deps_multi(subtasks, sub_questions)

        return TaskPlan(
            subtasks=subtasks,
            merge_strategy="prioritized",
            max_parallel=min(5, len(subtasks)),
            adaptive_profile=get_profile_defaults(str(adaptive_profile.get("name", "balanced") or "balanced")),
            is_multi_question=True,
        )

    def __attach_deps_multi(self, sts: list[SubTask], sub_questions: list[dict[str, str]]) -> None:
        """Attach cross-question dependencies across all agent types."""
        if not sts or len(sub_questions) < 2:
            return
        sq_to_st: dict[str, SubTask] = {}
        for s in sts:
            if s.sub_question_id:
                sq_to_st[s.sub_question_id] = s

        # Reference words that imply dependency on previous results
        _DEP_REFERENCES = [
            "它们", "这些", "上述", "其", "该产品", "该结果",
            "基于以上", "根据以上", "根据上述", "在此基础上",
            "based on the above", "based on that", "these",
            "its", "their", "the above", "those results",
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
