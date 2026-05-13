from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

logger = logging.getLogger(__name__)

VALID_FORCE_MODES = frozenset(
    {
        "rag",
        "data_query",
        "data_analysis",
        "anomaly_tracking",
        "product",
        "rule_engine",
        "tool",
        "skills",
        "web",
        "vision",
    }
)

from agents.base import AgentResult
from agents.data_agent import DataAgent
from agents.rag_agent import RagAgent
from agents.registry import AgentRegistry
from agents.rule_engine_agent import RuleEngineAgent
from agents.skills_agent import SkillsAgent
from agents.vision_agent import VisionAgent
from agents.web_agent import WebAgent
from execution.tool_router.router import ToolRouter
from infra.config.settings import settings
from infra.message_bus.cognitive_event_bus import cognitive_event_bus
from infra.observability.runtime_metrics import runtime_metrics_store
from kernel.adaptive_profiles import get_profile_defaults
from kernel.clarification_gate import ClarificationGate
from kernel.cognition.task_model import TaskModel
from kernel.cognition.world_model import WorldModel
from kernel.context.query_rewriter import QueryRewriter
from kernel.critic_engine.engine import CriticEngine
from kernel.critic_engine.models import CriticInput
from kernel.dialogue_state_tracker import DialogueStateTracker
from kernel.dispatcher import Dispatcher
from kernel.reference_resolver import ReferenceResolver
from kernel.refine_planner import RefinePlanner
from kernel.result_ref_builder import ResultRefBuilder
from kernel.epistemology.annotator import ContentAnnotator
from kernel.epistemology.validator import OutputValidator
from kernel.fusion_engine.engine import FusionEngine
from kernel.fusion_engine.models import FusionInput, ToolResult
from kernel.fusion_engine.sequence_fusion import SequenceFusionEngine
from kernel.fusion_engine.sequence_models import SequenceFusionInput
from kernel.identity.system_identity import CANONICAL_IDENTITY_RESPONSE, is_identity_user_query
from kernel.json_parser import parse_llm_json
from kernel.plan_agent import PlanAgent
from model.llm_adapter.base import LLMMessage
from safety.masking.ner_masker import NERMasker, get_ner_masker
from safety.xai.cognitive_trace import get_cognitive_tracer
from model.model_gateway.gateway import LLMRole, get_model_gateway

_MATH_EXPR = re.compile(r"[\d]+\s*[\+\-\*\/\^]\s*[\d]")


def _looks_like_math(text: str) -> bool:
    return bool(_MATH_EXPR.search((text or "").strip()))


class ToolAgent:
    agent_type = "tool"

    def _parse_payload(self, out: str) -> tuple[str, dict[str, Any]]:
        raw = (out or "").strip()
        if not raw:
            return "tool", {"type": "tool", "text": ""}

        parsed: Any = None
        try:
            parsed = json.loads(raw)
        except Exception:
            try:
                parsed = ast.literal_eval(raw)
            except Exception:
                parsed = None

        if isinstance(parsed, dict):
            if "time" in parsed and "timestamp" in parsed:
                return "datetime", {"type": "time", **parsed}
            if "city" in parsed and ("temperature" in parsed or "weather" in parsed):
                return "weather", {"type": "weather", **parsed}
            return "tool", {"type": "tool", "text": raw, "raw": parsed}

        return "tool", {"type": "tool", "text": raw}

    async def execute(self, task):
        from agents.base import AgentResult

        try:
            router = ToolRouter()
            out = await router.execute(
                intent=task.query, query=task.query, session_id=task.session_id or ""
            )
            tool_name = "tool"
            if not out:
                q = (task.query or "").lower()
                if any(k in q for k in ["几点", "时间", "time", "日期", "date"]):
                    tool_name = "datetime"
                    out = await router.execute_by_name(
                        name="datetime", query=task.query, session_id=task.session_id or ""
                    )
                elif any(k in q for k in ["天气", "weather", "温度", "下雨"]):
                    tool_name = "get_weather"
                    out = await router.execute_by_name(
                        name="get_weather", query=task.query, session_id=task.session_id or ""
                    )
                elif _looks_like_math(q):
                    tool_name = "calculator"
                    out = await router.execute_by_name(
                        name="calculator", expression=q, session_id=task.session_id or ""
                    )

            raw = str(out or "").strip()
            low = raw.lower()
            if (
                (not raw)
                or low.startswith("error:")
                or low.startswith("tool error")
                or low.startswith("weather error")
                or low.startswith("web search error")
                or low.startswith("web search unavailable")
            ):
                return AgentResult(
                    task_id=task.task_id,
                    agent_type="tool",
                    status="error",
                    content="",
                    confidence=0.0,
                    error=raw or "no tool matched",
                )

            parsed_tool_name, payload = self._parse_payload(raw)
            if parsed_tool_name != "tool":
                tool_name = parsed_tool_name

            text_preview = payload.get("text") if isinstance(payload, dict) else None
            if tool_name == "datetime" and isinstance(payload, dict):
                time_str = payload.get("time") or payload.get("datetime") or ""
                tz_str = payload.get("timezone") or ""
                text_preview = f"当前时间：{time_str}" + (f"（{tz_str}）" if tz_str else "")
            elif tool_name == "tool" and isinstance(payload, dict) and "time" in payload:
                time_str = payload.get("time") or ""
                tz_str = payload.get("timezone") or ""
                text_preview = f"当前时间：{time_str}" + (f"（{tz_str}）" if tz_str else "")
            elif not text_preview and isinstance(payload, dict):
                text_preview = json.dumps(payload, ensure_ascii=False)

            return AgentResult(
                task_id=task.task_id,
                agent_type="tool",
                status="success",
                content=str(text_preview or out)[:1200],
                confidence=0.88,
                metadata={
                    "normalized": True,
                    "tool_name": tool_name,
                    "payload": payload,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return AgentResult(
                task_id=task.task_id, agent_type="tool", status="error", content="", error=str(exc)
            )


@dataclass
class OrchestratorV4Request:
    query: str
    session_id: str = ""
    user_id: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    trace_ctx: Any = None
    conversation_state: Any = None  # ConversationState | None


@dataclass
class OrchestratorV4Response:
    content: str
    route: str
    strategy: str
    passed_validation: bool
    validation_score: float
    hallucination_risk: float
    intent_category: str
    metadata: dict[str, Any] = field(default_factory=dict)
    state_patch: dict[str, Any] | None = None
    result_refs: list[dict[str, Any]] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""


class CognitiveOrchestratorV4:
    def _get_adaptive_profile(
        self, query: str, user_tags: list[str] | None = None
    ) -> dict[str, Any]:
        q = (query or "").lower()
        profile_name = "balanced"
        if not bool(settings.kernel_adaptive_mode_enabled):
            return get_profile_defaults(profile_name)
        # Honor user_tags: if user prefers speed/quality, bias the profile
        tags = [t.lower() for t in (user_tags or [])]
        if any(k in q for k in ["最新", "新闻", "实时", "联网", "今天", "weather"]):
            profile_name = "speed"
        elif any(k in q for k in ["文档", "总结", "归纳", "pdf", "docx", "根据文档", "从文档"]):
            profile_name = "quality"
        elif any(k in q for k in ["查询", "统计", "报表", "销量", "订单", "sql", "数据库"]):
            profile_name = "quality"
        elif "speed" in tags:
            profile_name = "speed"
        elif "quality" in tags:
            profile_name = "quality"
        profile = get_profile_defaults(profile_name)

        # Apply user preference tags to profile when profiling is enabled
        if bool(getattr(settings, "kernel_user_profiling_enabled", False)) and user_tags:
            try:
                from kernel.adaptive_profiles import apply_user_tags
                profile = apply_user_tags(profile, user_tags)
            except Exception:
                pass

        return profile

    def _sanitize_user_output(self, text: str, pii_mapping: dict[str, str] | None = None) -> str:
        import re

        content = (text or "").strip()
        if not content:
            return ""

        # Unmask PII placeholders if mapping is provided
        if pii_mapping:
            try:
                masker = get_ner_masker()
                content = masker.unmask_output(content, pii_mapping)
            except Exception:
                pass

        # Remove explicit internal source markers like [tool]/[web_search]/[sql] and Chinese labels
        content = re.sub(
            r"\[(tool|web_search|sql|document|memory|历史记忆|文档片段|数据库查询结果|网络搜索结果|天气信息|时间信息|LLMWiki增强问答|技能匹配)\]\s*",
            "",
            content,
            flags=re.IGNORECASE,
        )

        # Remove evidence-level emoji prefixes from annotation rendering
        content = re.sub(r"[📊📄🔗🧠💡⚠️ℹ️]\s*", "", content)

        # Remove inline JSON-like blobs to avoid exposing internal payloads.
        content = re.sub(
            r"\{\s*\"(?:normalized|tool_name|payload|raw|metadata|agent_results|plan)\"[\s\S]*?\}",
            "",
            content,
        )

        # Remove common tool schema leakage lines.
        leakage_patterns = [
            r"请提供\s*JSON[:：]?.*",
            r"Tool\s+error.*",
            r"Web\s+search\s+(error|unavailable).*",
            r"Weather\s+error.*",
        ]
        for p in leakage_patterns:
            content = re.sub(p, "", content, flags=re.IGNORECASE)

        content = re.sub(r"\n{3,}", "\n\n", content).strip()
        if not content:
            return "抱歉，我暂时无法生成有效的回答。请尝试换个方式提问，或提供更多背景信息，我会尽力帮你解答。"
        return content

    # ── Multi-question handling ─────────────────────────────────────────
    _MULTI_Q_SEPARATORS_RE = r"[；;]|[，,]\s*(?:并|同时|另外|此外|还有|再分析|再查询|再告诉)"
    _MULTI_Q_HINTS = [
        "第一个",
        "第二个",
        "第三个",
        "第一",
        "第二",
        "第三",
        "并告诉我",
        "同时告诉我",
        "另外",
        "此外",
        "还有",
        "再分析",
        "再查询",
        "再告诉我",
    ]
    _MAX_MULTI_QUESTIONS = 5

    # Domain classification keywords for sub-questions
    _DOMAIN_DATA_KW = [
        "查询",
        "统计",
        "报表",
        "销量",
        "订单",
        "数据库",
        "sql",
        "表",
        "字段",
        "列",
        "聚合",
        "分组",
        "金额",
        "收入",
        "分布",
        "图表",
        "饼图",
        "柱状图",
        "排名",
        "top",
        "总数",
        "条数",
    ]
    _DOMAIN_RAG_KW = [
        "文档",
        "手册",
        "知识库",
        "总结",
        "归纳",
        "pdf",
        "doc",
        "附件",
        "政策",
        "规范",
        "记忆",
        "读取",
        "读一下",
        "上传文档",
        ".pdf",
        ".doc",
        ".docx",
        ".txt",
        ".md",
        "提炼",
        "根据文档",
        "从文档",
    ]
    _DOMAIN_WEB_KW = [
        "最新",
        "新闻",
        "今天",
        "实时",
        "联网",
        "搜索",
        "weather",
        "气温",
        "降雨",
        "热搜",
        "资讯",
        "发生",
        "事件",
        "动态",
    ]
    _DOMAIN_TOOL_KW = [
        "时间",
        "几点",
        "天气",
        "计算",
        "代码",
        "执行",
        "画图",
        "生成图片",
        "翻译",
        "单位换算",
        "倒计时",
    ]
    # Factual/trivia patterns — these should NOT go to RAG, prefer web or tool
    _FACTUAL_Q_PATTERNS = [
        "首都",
        "国家",
        "哪里",
        "是谁",
        "哪个",
        "什么时候",
        "多少",
        "多大",
        "多远",
        "什么",
        "位于",
        "属于",
    ]

    def _classify_sub_question_domain(self, text: str) -> str:
        """Classify a single sub-question into a domain."""
        t = (text or "").lower()
        scores: dict[str, int] = {
            "data_query": 0,
            "document_retrieval": 0,
            "web_search": 0,
            "tool_execution": 0,
            "general_qa": 0,
        }
        for kw in self._DOMAIN_DATA_KW:
            if kw in t:
                scores["data_query"] += 1
        for kw in self._DOMAIN_RAG_KW:
            if kw in t:
                scores["document_retrieval"] += 1
        for kw in self._DOMAIN_WEB_KW:
            if kw in t:
                scores["web_search"] += 1
        for kw in self._DOMAIN_TOOL_KW:
            if kw in t:
                scores["tool_execution"] += 1
        # Factual/trivia patterns: if the question looks like a factual query
        # AND no document/data signals are present, boost web_search so it
        # doesn't fall through to general_qa or get misrouted to RAG.
        has_factual = any(p in t for p in self._FACTUAL_Q_PATTERNS)
        if has_factual and scores["document_retrieval"] == 0 and scores["data_query"] == 0:
            scores["web_search"] = max(scores["web_search"], 2)
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "general_qa"

    async def _detect_and_split_multi_question(self, query: str) -> list[dict[str, str]] | None:
        """Detect multi-question and return sub-questions, or None for single question."""
        q = (query or "").strip()

        # Strongest signal: multiple question marks — check before length filter
        qm_count = q.count("？") + q.count("?")
        if qm_count >= 2:
            return await self._split_multi_question(q)

        # Length filter
        if len(q) < 15:
            return None

        # Check multi-question hints
        if any(hint in q for hint in self._MULTI_Q_HINTS):
            return await self._split_multi_question(q)

        # Use IntentEngine multi_step as secondary signal
        try:
            from kernel.intent_engine.engine import IntentEngine

            intent = await IntentEngine().parse(q)
            if intent.multi_step:
                return await self._split_multi_question(q)
        except Exception:
            pass

        return None

    async def _split_multi_question(self, query: str) -> list[dict[str, str]] | None:
        """Split a query into sub-questions with domain classification."""
        import re

        def _make_result(texts: list[str]) -> list[dict[str, str]]:
            return [
                {
                    "id": f"q{i+1}",
                    "text": t,
                    "display_order": i + 1,
                    "domain": self._classify_sub_question_domain(t),
                }
                for i, t in enumerate(texts[: self._MAX_MULTI_QUESTIONS])
            ]

        # Try question marks first — the most explicit delimiter
        qm_parts = re.split(r"[？?]\s*", query)
        qm_parts = [s.strip() for s in qm_parts if s.strip() and len(s.strip()) > 2]
        if len(qm_parts) >= 2:
            return _make_result(qm_parts)

        # Try numbered patterns
        numbered = re.split(r"(?:^|\n)\s*(?:\d+[\.\、\)]|第[一二三四五六七八九])", query)
        numbered = [s.strip() for s in numbered if s.strip() and len(s.strip()) > 5]
        if len(numbered) >= 2:
            return _make_result(numbered)

        # Try Chinese semicolons
        if "；" in query:
            parts = [s.strip() for s in query.split("；") if s.strip() and len(s.strip()) > 5]
            if len(parts) >= 2:
                return _make_result(parts)

        # Try logical connectors
        logical_split = re.split(
            r"[，,]\s*(?:并|同时|另外|此外|还有|再分析|再查询|再告诉)\s*", query
        )
        logical_split = [s.strip() for s in logical_split if s.strip() and len(s.strip()) > 8]
        if len(logical_split) >= 2:
            return _make_result(logical_split)

        # Fall back to LLM splitting
        return await self._split_by_llm(query)

    async def _split_by_llm(self, query: str) -> list[dict[str, str]] | None:
        """Use PLANNING LLM to split a complex query into sub-questions."""
        prompt = (
            "你是一个问题分解器。将用户的复合问题拆分为独立的子问题列表，输出 JSON。\n"
            "规则：\n"
            "- 每个子问题应是一个独立、可单独回答的完整问题。\n"
            "- domain 必须从以下选项中选择：\n"
            "  · data_query — 查询数据库、统计报表、销量、订单等结构化数据\n"
            "  · document_retrieval — 检索文档、知识库、手册、总结归纳等\n"
            "  · web_search — 搜索最新新闻、实时信息、天气资讯等\n"
            "  · tool_execution — 时间查询、天气、计算、代码执行、翻译等工具操作\n"
            "  · general_qa — 通用问答、分析、建议等\n"
            "- 如果用户只提了一个问题，返回包含该问题的单元素数组。\n"
            '- 输出格式：{"questions": [{"id": "q1", "text": "...", "domain": "..."}]}\n'
            f"用户输入：{query}"
        )
        try:
            gw = get_model_gateway()
            resp = await gw.complete(
                [LLMMessage(role="user", content=prompt)],
                role=LLMRole.PLANNING,
                temperature=0.0,
                max_tokens=400,
            )
            text = (resp.content or "").strip()
            parsed = parse_llm_json(text)
            if not parsed or not isinstance(parsed, dict):
                return None
            data = parsed
            questions = data.get("questions", [])
            if isinstance(questions, list) and len(questions) >= 2:
                result = []
                for i, q_data in enumerate(questions[: self._MAX_MULTI_QUESTIONS]):
                    if isinstance(q_data, dict):
                        result.append(
                            {
                                "id": q_data.get("id", f"q{i+1}"),
                                "text": q_data.get("text", ""),
                                "display_order": i + 1,
                                "domain": q_data.get("domain", "general_qa"),
                            }
                        )
                if len(result) >= 2:
                    return result
        except Exception:
            pass
        return None

    async def _process_multi_question(
        self,
        req: OrchestratorV4Request,
        sub_questions: list[dict[str, str]],
        data_source_context: dict[str, Any],
        adaptive_profile: dict[str, Any],
        t0: float,
        trace_id: str,
        event_cb=None,
    ) -> OrchestratorV4Response:
        """Full pipeline for multi-question queries."""
        if trace_id:
            await cognitive_event_bus.publish(
                cognitive_event_bus.emit_planning(
                    trace_id=trace_id,
                    payload={
                        "action": "orchestrator.multi_question.start",
                        "query": req.query,
                        "sub_question_count": len(sub_questions),
                    },
                    session_id=req.session_id,
                    user_id=req.user_id,
                    source="orchestrator_v4",
                )
            )

        # Step 1: Generate multi-plan
        # ── Normalize conversation_state ──────────────────────────────
        _multi_conv_state_dict: dict[str, Any] | None = None
        if req.conversation_state is not None:
            if hasattr(req.conversation_state, "to_db_dict"):
                _multi_conv_state_dict = req.conversation_state.to_db_dict()
            elif isinstance(req.conversation_state, dict):
                _multi_conv_state_dict = req.conversation_state

        plan = await self.plan_agent.generate_multi_plan(
            sub_questions,
            context={
                "metadata": req.metadata,
                "adaptive_profile": adaptive_profile,
                "data_source_context": data_source_context,
                "conversation_history": req.history,
                "conversation_state": _multi_conv_state_dict,
            },
        )

        # Patch session/user into subtask params
        for s in plan.subtasks:
            if s.params is None:
                s.params = {}
            s.params["session_id"] = req.session_id
            s.params["user_id"] = req.user_id
            if s.sub_question_id:
                s.params["sub_question_id"] = s.sub_question_id
                s.params["display_order"] = s.display_order

        # Step 2: Dispatch agents
        agent_results = await self.dispatcher.dispatch(plan, event_cb=event_cb)

        # Step 3: Enrich agent_results with sub_question_id from the plan
        for i, r in enumerate(agent_results):
            if i < len(plan.subtasks):
                sq_id = plan.subtasks[i].sub_question_id
                disp_order = plan.subtasks[i].display_order
                if sq_id:
                    md = dict(r.metadata or {})
                    md["sub_question_id"] = sq_id
                    md["display_order"] = disp_order
                    r.metadata = md

        # Step 4: Sequence fusion
        # Build background_materials from attachment contexts
        attachment_contexts = req.metadata.get("attachment_contexts", [])
        background_materials = ""
        if attachment_contexts:
            bg_parts = [
                str(ac["content"])
                for ac in attachment_contexts
                if isinstance(ac, dict) and ac.get("content")
            ]
            if bg_parts:
                background_materials = "\n\n---\n\n".join(bg_parts)

        fusion_engine = SequenceFusionEngine()
        fusion_output = await fusion_engine.run(
            SequenceFusionInput(
                query=req.query,
                sub_questions=sub_questions,
                agent_results=agent_results,
                background_materials=background_materials,
            )
        )

        answer = fusion_output.content
        if not (answer or "").strip():
            answer = "抱歉，暂时无法生成完整的回答。请尝试逐个提问，或提供更详细的信息。"

        total_latency_ms = int((monotonic() - t0) * 1000)
        metrics = {
            "first_token_ms": total_latency_ms,
            "orchestrator_latency_ms": total_latency_ms,
            "supervisor_retry_count": 0,
            "agent_count": len(agent_results),
            "avg_agent_latency_ms": int(total_latency_ms / max(1, len(agent_results))),
        }
        runtime_metrics_store.record(metrics)

        if trace_id:
            await cognitive_event_bus.publish(
                cognitive_event_bus.emit_learning(
                    trace_id=trace_id,
                    payload={
                        "action": "orchestrator.process.completed",
                        "route": "multi_question",
                        "validation_score": fusion_output.confidence,
                        "passed_validation": True,
                        "agent_count": len(agent_results),
                        "sub_question_count": len(sub_questions),
                    },
                    session_id=req.session_id,
                    user_id=req.user_id,
                    source="orchestrator_v4",
                )
            )

        # ── Build state_patch for multi-question ──────────────────────
        _mq_state_patch: dict[str, Any] = {
            "last_user_goal": req.query,
            "last_assistant_summary": (answer or "")[:300],
            "last_plan": {
                "subtasks": [
                    {
                        "agent_type": s.agent_type,
                        "query": s.query,
                        "params": s.params,
                        "sub_question_id": s.sub_question_id,
                    }
                    for s in plan.subtasks
                ],
                "merge_strategy": plan.merge_strategy,
                "max_parallel": plan.max_parallel,
                "is_multi_question": True,
            },
            "last_results": [
                {
                    "agent_type": r.agent_type,
                    "status": r.status,
                    "content": (r.content or "")[:300],
                    "result_refs": [
                        {
                            "ref_id": ref.ref_id,
                            "type": ref.type,
                            "title": ref.title,
                            "summary": ref.summary,
                        }
                        for ref in ResultRefBuilder.build_from_agent_result(
                            r,
                            plan.subtasks[i].query if i < len(plan.subtasks) else "",
                        )
                    ],
                }
                for i, r in enumerate(agent_results)
            ],
        }
        if agent_results:
            _mq_all_refs = ResultRefBuilder.build_from_task_results(
                agent_results, plan.subtasks
            )
            _mq_state_patch["last_result_refs"] = _mq_all_refs

        mq_conversation_summary = req.metadata.get("conversation_summary", "")
        if mq_conversation_summary:
            _mq_state_patch["conversation_summary"] = mq_conversation_summary

        _mq_result_refs: list[dict[str, Any]] = []
        for r in agent_results:
            if isinstance(r.metadata, dict):
                refs = r.metadata.get("result_refs", [])
                if isinstance(refs, list):
                    _mq_result_refs.extend(refs)

        return OrchestratorV4Response(
            content=answer,
            route="multi_question",
            strategy="sequence_fusion",
            passed_validation=True,
            validation_score=fusion_output.confidence,
            hallucination_risk=0.0,
            intent_category="multi_question",
            state_patch=_mq_state_patch,
            result_refs=_mq_result_refs,
            metadata={
                "orchestrator_version": "v4",
                "adaptive_profile": adaptive_profile,
                "plan": {
                    "subtasks": [
                        {
                            "agent_type": s.agent_type,
                            "query": s.query,
                            "sub_question_id": s.sub_question_id,
                            "display_order": s.display_order,
                        }
                        for s in plan.subtasks
                    ],
                    "merge_strategy": plan.merge_strategy,
                    "max_parallel": plan.max_parallel,
                    "is_multi_question": True,
                },
                "agent_results": [r.model_dump(mode="json") for r in agent_results],
                "fusion": {
                    "type": "sequence",
                    "confidence": fusion_output.confidence,
                    "context": fusion_output.content,
                },
                "per_question_results": [
                    {
                        "sub_question_id": pq.sub_question_id,
                        "question_text": pq.question_text,
                        "display_order": pq.display_order,
                        "status": pq.status,
                        "error_reason": pq.error_reason,
                    }
                    for pq in fusion_output.per_question_results
                ],
                "sub_questions": sub_questions,
                "metrics": metrics,
            },
        )

    async def _llm_fallback_answer(
        self, req: OrchestratorV4Request, memory_context: list[dict[str, Any]] | None = None
    ) -> str:
        gw = get_model_gateway()
        system = (
            "你是一个热情、可靠、有温度的智能助手。请用自然、亲切、口语化的中文直接回答用户问题，语气像一位乐于助人的好朋友。"
            "避免提及自身身份或底层模型，不要自称 OpenTrace、Qwen、ChatGPT 等。"
            "回答时尽量饱满完整：先给出核心结论，再补充必要的细节、依据或操作建议，让用户看完就能用上。"
            "在适当的时候使用温和的语气词（如「呢」「哦」「哈」），让对话更轻松自然，但不要过度。"
            "如果涉及数据库操作但无法执行，请说明原因并给出建议的 SQL 语句。"
            "不要以「我是…」开头，直接切入正题。"
            "如果用户要求编写演示性代码（如游戏、可视化、交互效果），优先输出自包含的 HTML+JavaScript 代码，"
            "使其可直接在浏览器中运行展示，不要使用 Python/pygame 等需要额外安装依赖的方案。"
            "代码应完整可用，不要省略关键部分。"
        )
        msgs = [LLMMessage(role="system", content=system)]

        # Inject memory context as additional background if available
        memory_context = memory_context or []
        if memory_context:
            memory_lines = []
            for mc in memory_context[:5]:
                if isinstance(mc, dict) and mc.get("content"):
                    src = mc.get("source", "memory")
                    memory_lines.append(f"[{src}] {str(mc['content'])[:400]}")
            if memory_lines:
                memory_preamble = (
                    "以下是与当前对话可能相关的历史记忆片段，仅供参考：\n" + "\n".join(memory_lines)
                )
                msgs.append(LLMMessage(role="system", content=memory_preamble))

        for h in (req.history or [])[-6:]:
            role = "assistant" if str(h.get("role", "")).lower() == "assistant" else "user"
            content = str(h.get("content", "")).strip()
            if content:
                msgs.append(LLMMessage(role=role, content=content))

        # Inject attachment content as background material
        attachment_contexts = req.metadata.get("attachment_contexts", [])
        if attachment_contexts:
            bg_parts = [
                str(ac["content"])
                for ac in attachment_contexts
                if isinstance(ac, dict) and ac.get("content")
            ]
            if bg_parts:
                bg_text = "\n\n---\n\n".join(bg_parts)
                user_message = (
                    "用户上传了以下文件作为背景材料，请将材料内容作为回答的知识背景：\n\n"
                    f"--- 背景材料开始 ---\n{bg_text[:6000]}\n--- 背景材料结束 ---\n\n"
                ) + req.query
                msgs.append(LLMMessage(role="user", content=user_message))
            else:
                msgs.append(LLMMessage(role="user", content=req.query))
        else:
            msgs.append(LLMMessage(role="user", content=req.query))
        resp = await gw.complete(msgs, role=LLMRole.QUERY, temperature=0.35, max_tokens=4096)
        return (
            resp.content or ""
        ).strip() or "很抱歉，我暂时无法处理这个请求。请尝试补充更多细节或换一种方式描述你的问题，我会继续帮你。"

    def _grounded_answer_style(
        self,
        query: str,
        evidence_count: int = 0,
        user_style_hints: dict[str, str | None] | None = None,
    ) -> tuple[str, int]:
        q = (query or "").strip()
        is_complex = any(
            k in q.lower()
            for k in [
                "步骤",
                "如何",
                "怎么",
                "流程",
                "原因",
                "总结",
                "归纳",
                "说明",
                "对比",
                "区别",
                "为什么",
                "分析",
                "解释",
            ]
        )
        # Apply user conciseness preference multiplier
        conciseness_mult = 1.0
        hints = user_style_hints or {}
        user_conciseness = hints.get("conciseness")
        if user_conciseness == "concise":
            conciseness_mult = 0.55
        elif user_conciseness == "detailed":
            conciseness_mult = 1.6

        if evidence_count <= 1:
            base = (
                "请输出简洁但完整的中文回答：先给结论，再补充必要细节。语气要亲切自然，像在跟朋友聊天。"
                "合理使用「呢」「哈」等温和语气词让对话轻松有温度，但不要刻意堆砌。"
                "如果信息较少，坦诚说明已确认和不确定的部分，并给出实用的下一步建议，让用户感到你真心在帮他解决问题。"
            )
            max_tok = max(512, min(8192, int((2048 if not is_complex else 3072) * conciseness_mult)))
            return (base, max_tok)
        if evidence_count <= 3 and not is_complex:
            max_tok = max(512, min(8192, int(3072 * conciseness_mult)))
            return (
                "请输出自然、完整、有温度的中文回答：先给结论，再展开说明关键依据。"
                "回答应适度分段，必要时补充注意事项和建议，不要只做干巴巴的摘要。语气亲切自然，像一位知识丰富的同事在耐心解答。"
                "适当使用口语化的过渡和温和的表达，让回答读起来轻松、有人情味。",
                max_tok,
            )
        if is_complex or evidence_count >= 4:
            max_tok = max(512, min(8192, int(4096 * conciseness_mult)))
            return (
                "请输出结构化、饱满、可交付的中文回答：先给结论，再分段展开说明。"
                "建议包含背景、关键依据、步骤/条件、注意事项、边界和可执行建议。"
                "语言要自然顺滑，段落之间要有顺畅的衔接，不要重复堆砌证据。"
                "语气保持专业但不生硬，适当融入温和的表达使回答更有温度，"
                "让回答读起来像一篇经过人工精心整理的高质量文档，可直接交付给用户阅读。",
                max_tok,
            )
        max_tok = max(512, min(8192, int(3072 * conciseness_mult)))
        return (
            "请输出自然、完整、饱满的中文回答：先给结论，再展开说明关键依据和细节。"
            "必要时补充步骤、条件、注意事项和边界。语言要自然、连贯、有温度，像人工精心整理后的最终稿。"
            "适当使用口语化的表达和温和的语气，让回答有亲和力。"
            "不要过于简短，尽量做到可直接使用，读完让人觉得你真正帮到了他。",
            max_tok,
        )

    async def _llm_grounded_answer(
        self,
        query: str,
        evidence_text: str,
        history: list[dict[str, str]] | None = None,
        background_materials: str | None = None,
        user_style_hints: dict[str, str | None] | None = None,
    ) -> str:
        gw = get_model_gateway()
        style_hint, max_tokens = self._grounded_answer_style(
            query, evidence_count=max(0, evidence_text.count("[")),
            user_style_hints=user_style_hints,
        )
        system = (
            "你是知识问答助手。你的目标是把检索或查询到的信息整理成一段自然、完整、有温度的中文回答。"
            "请先直接给出结论，再展开说明关键依据和细节，必要时补充步骤、条件、注意事项和边界。"
            "语言要顺滑、专业但不生硬，像一位知识丰富的同事在认真回答——亲切、靠谱、不端着。"
            "在保持专业的同时，适当使用口语化的过渡词和温和的语气，让回答读起来像是一次愉快的对话而不是一份干巴巴的报告。"
            "段落之间要有自然衔接，避免重复和机械感，让回答读起来像是人工精心整理后的最终稿。"
            "不要只复述证据，也不要过度简短；在证据充分时，回答应当完整、清晰、可直接给用户使用。"
            "如果证据不足，必须明确说明缺失点，并告诉用户还需要补充什么信息，语气要让人感到你是真心在帮他。"
            "如果证据中包含 [历史记忆] 标记的内容，请自然融入回答中，让回复保持连贯、有上下文感。"
            "对于用户追问或引用之前对话的问题，优先利用记忆片段保持回答的一致性。"
            "禁止输出内部字段名、JSON 结构、检索分数、agent 名称或原始工具内容。"
        )
        msgs = [LLMMessage(role="system", content=system)]
        for h in (history or [])[-6:]:
            role = "assistant" if str(h.get("role", "")).lower() == "assistant" else "user"
            content = str(h.get("content", "")).strip()
            if content:
                msgs.append(LLMMessage(role=role, content=content))
        user_parts: list[str] = []
        if background_materials and background_materials.strip():
            user_parts.append(
                "用户上传了以下文件作为背景材料，请将材料内容作为回答的知识背景：\n\n"
                f"--- 背景材料开始 ---\n{background_materials.strip()[:6000]}\n--- 背景材料结束 ---"
            )
        user_parts.append(
            f"用户问题：{query}\n\n"
            f"检索证据：\n{evidence_text[:7000]}\n\n"
            f"输出要求：\n{style_hint}\n\n"
            "推荐结构：\n"
            "1. 结论/直接回答\n"
            "2. 详细说明\n"
            "3. 关键依据或要点\n"
            "4. 注意事项/下一步（如适用）"
        )
        msgs.append(LLMMessage(role="user", content="\n\n".join(user_parts)))
        resp = await gw.complete(
            msgs,
            role=LLMRole.QUERY,
            temperature=0.3,
            max_tokens=max_tokens,
        )
        return (resp.content or "").strip()

    def _build_rag_citations(self, agent_results: list) -> str:
        lines: list[str] = []
        seen: set[str] = set()
        for r in agent_results:
            if getattr(r, "agent_type", "") != "rag":
                continue
            meta = getattr(r, "metadata", None)
            if not isinstance(meta, dict):
                continue
            chunks = meta.get("chunks")
            if not isinstance(chunks, list):
                continue
            for i, c in enumerate(chunks[:5], start=1):
                if not isinstance(c, dict):
                    continue
                title = str(c.get("title") or "文档")
                cid = str(c.get("id") or f"chunk_{i}")
                text = str(c.get("text") or "").strip()
                key = f"{title}::{cid}"
                if key in seen:
                    continue
                seen.add(key)
                snippet = text[:60].replace("\n", " ")
                if snippet:
                    lines.append(f"- {title}（{cid}）：{snippet}…")
                else:
                    lines.append(f"- {title}（{cid}）")
        if not lines:
            return ""
        return "\n\n参考来源：\n" + "\n".join(lines)

    def _format_data_answer(self, query: str, agent_results: list) -> str:
        """Format data agent results into natural language."""
        for r in agent_results:
            if r.agent_type != "data" or not isinstance(r.metadata, dict):
                continue
            sql = str(r.metadata.get("sql", "")).strip()
            rows = r.metadata.get("rows")
            row_count = int(r.metadata.get("row_count", 0) or 0)

            if isinstance(rows, list) and rows:
                # Try to extract a single COUNT result
                first_row = rows[0]
                if isinstance(first_row, dict) and len(first_row) == 1:
                    col_name = list(first_row.keys())[0]
                    col_val = first_row[col_name]
                    if "count" in col_name.lower():
                        return f"根据查询结果，共有 {col_val} 条记录。"
                # Generic row display
                row_text = json.dumps(rows[:5], ensure_ascii=False)
                return f"查询已执行，共返回 {row_count} 行数据，以下是结果预览：\n\n{row_text}"

            if row_count == 0:
                return (
                    f"查询已执行完成，但没有找到匹配的数据。\n"
                    f"这通常是因为数据源中没有与「{query}」相关的表或字段，或者查询条件未能匹配到任何记录。\n\n"
                    "你可以试试：\n"
                    "- 在「数据源」页面确认一下已连接的表和字段结构是否正确\n"
                    "- 换一个更宽泛的查询条件，或者直接指定具体的表名"
                )

            if sql:
                return f"SQL 查询已成功执行。可以在数据查询面板中查看详细结果，执行的 SQL 如下：\n```sql\n{sql}\n```"

            return "数据查询已完成，如需查看更多细节，可以前往数据查询面板。"
        return ""

    def _format_rag_answer(
        self, answer: str, rag_chunks_count: int, rag_citations: list[dict[str, Any]]
    ) -> str:
        body = (answer or "").strip()
        if not body:
            return ""

        lines = [body]
        if rag_citations and rag_chunks_count > 1:
            insight_lines = []
            seen: set[str] = set()
            for c in rag_citations[:5]:
                title = str(c.get("title") or c.get("source_name") or "文档")
                snippet = str(c.get("snippet") or "")[:120].replace("\n", " ")
                key = f"{title}::{snippet}"
                if key in seen:
                    continue
                seen.add(key)
                if snippet:
                    insight_lines.append(f"- 从{title}来看，{snippet}")
                else:
                    insight_lines.append(f"- 参考了{title}中的相关内容")
            if insight_lines:
                lines.append("依据要点：")
                lines.extend(insight_lines)
        if rag_chunks_count <= 1:
            lines.append(
                "补充说明：当前检索到的相关证据比较少，以上结论是基于现有内容整理而成的。"
                "如果需要的话，我也可以帮你从更多文档或相关材料中补充细节。"
            )
        return "\n\n".join(lines).strip()

    def __init__(self, timeout_sec: int = 30, max_parallel: int = 5) -> None:
        self.plan_agent = PlanAgent()
        self.registry = AgentRegistry()
        self.registry.register(DataAgent())
        self.registry.register(WebAgent())
        if bool(settings.kernel_agent_rag_enabled):
            self.registry.register(RagAgent())
        self.registry.register(ToolAgent())
        self.registry.register(SkillsAgent())
        self.registry.register(RuleEngineAgent())
        if bool(getattr(settings, "kernel_agent_vision_enabled", False)):
            self.registry.register(VisionAgent())
        self.dispatcher = Dispatcher(
            self.registry,
            timeout_sec=timeout_sec,
            bus_enabled=bool(settings.kernel_agent_bus_enabled),
            bus_namespace=str(settings.kernel_agent_bus_namespace),
        )
        self.fusion_engine = FusionEngine()
        self.critic_engine = CriticEngine()
        self.annotator = ContentAnnotator()
        self.validator = OutputValidator()
        self.max_parallel = max_parallel

    async def process(self, req: OrchestratorV4Request, event_cb=None) -> OrchestratorV4Response:
        t0 = monotonic()
        tctx: Any = req.trace_ctx
        trace_id = str(
            req.metadata.get("trace_id")
            or req.metadata.get("request_id")
            or req.session_id
            or req.user_id
            or ""
        )
        root_span = tctx.start_span("planning") if tctx else ""

        # ── PII masking: mask sensitive entities in query before LLM calls ──
        pii_mapping: dict[str, str] = {}
        masked_query = req.query
        if bool(getattr(settings, "kernel_pii_masking_enabled", False)):
            try:
                masker = get_ner_masker()
                mask_result = masker.mask_input(req.query)
                masked_query = mask_result.masked
                pii_mapping = mask_result.mapping
            except Exception:
                pass

        # ── XAI cognitive tracer: start trace for audit trail ──
        xai_tracer = None
        xai_trace_id = ""
        if bool(getattr(settings, "kernel_xai_trace_enabled", False)):
            try:
                xai_tracer = get_cognitive_tracer()
                xai_trace_id = xai_tracer.start_trace(
                    req.session_id or "",
                    masked_query,
                    user_id=req.user_id or "",
                )
            except Exception:
                xai_tracer = None

        if trace_id:
            await cognitive_event_bus.publish(
                cognitive_event_bus.emit_planning(
                    trace_id=trace_id,
                    span_id=root_span,
                    payload={
                        "action": "orchestrator.process.start",
                        "query": req.query,
                        "session_id": req.session_id,
                        "user_id": req.user_id,
                        "metadata": {
                            k: v for k, v in req.metadata.items() if k not in {"user_preferences"}
                        },
                    },
                    session_id=req.session_id,
                    user_id=req.user_id,
                    source="orchestrator_v4",
                )
            )
        # Identity shortcut: only for pure identity queries, not multi-question
        _maybe_multi = (req.query or "").count("？") + (req.query or "").count("?") >= 2 or any(
            hint in (req.query or "") for hint in self._MULTI_Q_HINTS
        )
        if is_identity_user_query(req.query) and not _maybe_multi:
            if trace_id:
                await cognitive_event_bus.publish(
                    cognitive_event_bus.emit_learning(
                        trace_id=trace_id,
                        payload={"action": "orchestrator.identity.shortcut", "agent_count": 0},
                        session_id=req.session_id,
                        user_id=req.user_id,
                        source="orchestrator_v4",
                    )
                )
            elapsed_ms = int((monotonic() - t0) * 1000)
            metrics = {
                "first_token_ms": elapsed_ms,
                "orchestrator_latency_ms": elapsed_ms,
                "supervisor_retry_count": 0,
                "agent_count": 0,
                "avg_agent_latency_ms": 0,
            }
            runtime_metrics_store.record(metrics)
            if trace_id:
                await cognitive_event_bus.publish(
                    cognitive_event_bus.emit_learning(
                        trace_id=trace_id,
                        payload={
                            "action": "orchestrator.process.completed",
                            "route": "identity",
                            "validation_score": 1.0,
                            "passed_validation": True,
                            "agent_count": 0,
                        },
                        session_id=req.session_id,
                        user_id=req.user_id,
                        source="orchestrator_v4",
                    )
                )
            return OrchestratorV4Response(
                content=CANONICAL_IDENTITY_RESPONSE,
                route="identity",
                strategy="direct",
                passed_validation=True,
                validation_score=1.0,
                hallucination_risk=0.0,
                intent_category="identity",
                metadata={
                    "orchestrator_version": "v4",
                    "adaptive_profile": {
                        "name": "identity",
                        **self._get_adaptive_profile(req.query),
                    },
                    "plan": {"subtasks": [], "merge_strategy": "direct", "max_parallel": 0},
                    "agent_results": [],
                    "fusion": {
                        "confidence": 1.0,
                        "conflicts": [],
                        "context": CANONICAL_IDENTITY_RESPONSE,
                    },
                    "critic": {"feedback": "identity_shortcut"},
                    "execution_graph": {
                        "nodes": [],
                        "edges": [],
                        "state": {"identity_shortcut": True},
                    },
                    "metrics": metrics,
                },
            )

        task_model = TaskModel()
        task_model.init_from_query(req.query)
        task_model.add_hypothesis(
            "初始假设：可通过现有证据回答用户问题", confidence=0.7, source="inference"
        )

        world_model = WorldModel()
        grounded_entities = world_model.ground_query(req.query)

        user_tags: list[str] = req.metadata.get("user_preferences", []) or []
        user_preference_tags: list[str] = req.metadata.get("user_preference_tags", []) or []
        if isinstance(user_tags, str):
            user_tags = [user_tags]
        if isinstance(user_preference_tags, str):
            user_preference_tags = [user_preference_tags]
        all_tags = list(set(user_tags + user_preference_tags))

        # Generate user style hints from preference tags
        user_style_hints: dict[str, str | None] | None = None
        if bool(getattr(settings, "kernel_user_profiling_enabled", False)) and all_tags:
            try:
                from kernel.adaptive_profiles import user_tags_to_style_hints
                user_style_hints = user_tags_to_style_hints(all_tags)
            except Exception:
                pass

        adaptive_profile = self._get_adaptive_profile(req.query, user_tags=all_tags)
        data_source_context = {
            "data_source_id": req.metadata.get("data_source_id"),
            "data_source_name": req.metadata.get("data_source_name"),
            "database": req.metadata.get("data_source_database"),
            "source_type": req.metadata.get("data_source_source_type"),
            "schema": req.metadata.get("data_source_schema"),
        }
        force_mode: str | None = req.metadata.get("force_mode")
        if force_mode and force_mode not in VALID_FORCE_MODES:
            logger.warning("ignoring unknown force_mode=%r, falling back to PlanAgent", force_mode)
            force_mode = None

        # ── Normalize conversation_state ──────────────────────────────
        conv_state_dict: dict[str, Any] | None = None
        if req.conversation_state is not None:
            if hasattr(req.conversation_state, "to_db_dict"):
                conv_state_dict = req.conversation_state.to_db_dict()
            elif isinstance(req.conversation_state, dict):
                conv_state_dict = req.conversation_state

        # ── DST: resolve short/ambiguous follow-up queries ────────────
        dialogue_state = None
        resolved_query = req.query
        if not force_mode:
            try:
                dst = DialogueStateTracker()
                prev_plan = conv_state_dict.get("last_plan") if conv_state_dict else None
                prev_results = conv_state_dict.get("last_results") if conv_state_dict else None
                dialogue_state = await dst.track(
                    req.query,
                    previous_plan=prev_plan,
                    previous_results=prev_results,
                    history=req.history,
                )
                if dialogue_state.resolved_query and dialogue_state.resolved_query != req.query:
                    resolved_query = dialogue_state.resolved_query
            except Exception:
                dialogue_state = None
                resolved_query = req.query

        # ── ReferenceResolver: detect corrections, index/type references ──
        reference_result = None
        if not force_mode and req.conversation_state is not None:
            try:
                resolver = ReferenceResolver()
                reference_result = await resolver.resolve_with_llm(
                    req.query,
                    req.conversation_state,
                    result_refs=None,
                )
                if reference_result.confidence >= 0.5:
                    if reference_result.resolved_query and reference_result.resolved_query != req.query:
                        resolved_query = reference_result.resolved_query
            except Exception:
                reference_result = None

        # Multi-question detection (only when not in force_mode)
        if not force_mode:
            multi_q_result = await self._detect_and_split_multi_question(req.query)
            if multi_q_result:
                return await self._process_multi_question(
                    req,
                    multi_q_result,
                    data_source_context,
                    adaptive_profile,
                    t0,
                    trace_id,
                    event_cb,
                )

        # ── Correction path: RefinePlanner for incremental re-plan ─────
        correction_plan = None
        correction_reused: dict[int, Any] = {}
        correction_replaced_indices: list[int] = []
        if (
            not force_mode
            and reference_result is not None
            and reference_result.turn_type == "correction"
            and reference_result.confidence >= 0.6
            and conv_state_dict
            and conv_state_dict.get("last_plan")
        ):
            try:
                # Reconstruct previous TaskPlan from conversation_state
                prev_plan_dict = conv_state_dict["last_plan"]
                prev_subtasks = prev_plan_dict.get("subtasks", [])
                if prev_subtasks:
                    from kernel.plan_agent import SubTask, TaskPlan

                    reconstructed_subtasks = [
                        SubTask(
                            agent_type=s.get("agent_type", "rag"),
                            query=s.get("query", req.query),
                            params=s.get("params", {}),
                        )
                        for s in prev_subtasks
                    ]
                    previous_plan = TaskPlan(
                        subtasks=reconstructed_subtasks,
                        merge_strategy=prev_plan_dict.get("merge_strategy", "direct"),
                        max_parallel=prev_plan_dict.get("max_parallel", 3),
                    )

                    # Build AgentResult list from last_results
                    prev_results_list = conv_state_dict.get("last_results", [])
                    previous_results = []
                    for pr in prev_results_list:
                        from agents.base import AgentResult

                        previous_results.append(
                            AgentResult(
                                task_id="",
                                agent_type=pr.get("agent_type", ""),
                                status=pr.get("status", "success"),
                                content=pr.get("content", ""),
                                confidence=0.75,
                            )
                        )

                    # Detect correction and refine plan
                    refine_planner = RefinePlanner()
                    correction_intent = await refine_planner.detect_correction(
                        req.query, previous_plan
                    )
                    if correction_intent.is_correction and correction_intent.confidence >= 0.6:
                        refined = refine_planner.refine_plan(
                            correction_intent,
                            previous_plan,
                            previous_results,
                            req.query,
                        )
                        if refined.replaced_indices:
                            correction_plan = refined.plan
                            correction_reused = refined.reused_results
                            correction_replaced_indices = refined.replaced_indices
                            resolved_query = correction_intent.corrected_query or req.query
            except Exception:
                correction_plan = None
                correction_reused = {}
                correction_replaced_indices = []
        # ── End correction path ──────────────────────────────────────────

        # Build plan: either force-route directly, or let PlanAgent decide
        if force_mode:
            from kernel.plan_agent import SubTask, TaskPlan

            agent_map = {
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
            agent_type = agent_map.get(force_mode, "rag")

            # Guard: data agents require a valid data_source_id
            if agent_type == "data" and not data_source_context.get("data_source_id"):
                elapsed_ms = int((monotonic() - t0) * 1000)
                return OrchestratorV4Response(
                    content="未找到可用的数据源。请先在「数据源」页面配置数据源，或使用 /rag 模式查询。",
                    route="force_mode_missing_source",
                    strategy="error",
                    passed_validation=True,
                    validation_score=0.0,
                    hallucination_risk=0.0,
                    intent_category=force_mode,
                    metadata={
                        "orchestrator_version": "v4",
                        "adaptive_profile": adaptive_profile,
                        "force_mode": force_mode,
                        "error": "missing_data_source",
                        "execution_graph": {
                            "nodes": [],
                            "edges": [],
                            "state": {"error": "no_data_source"},
                        },
                        "metrics": {
                            "first_token_ms": elapsed_ms,
                            "orchestrator_latency_ms": elapsed_ms,
                            "agent_count": 0,
                            "avg_agent_latency_ms": 0,
                        },
                    },
                )

            params: dict[str, Any] = {"session_id": req.session_id, "user_id": req.user_id}
            if agent_type == "skills":
                params["enabled_skills"] = True
            if agent_type == "rag":
                params.update(
                    {
                        "top_k": 8,
                        "sources": ["documents", "semantic_memory"],
                        "min_score": adaptive_profile["rag_min_score"],
                    }
                )
            elif agent_type == "data":
                params["data_source_id"] = data_source_context["data_source_id"]

            plan = TaskPlan(
                subtasks=[SubTask(agent_type=agent_type, query=req.query, params=params)],
                merge_strategy="direct",
                max_parallel=1,
            )
            plan.adaptive_profile = adaptive_profile
        else:
            if correction_plan is not None:
                plan = correction_plan
            else:
                plan = await self.plan_agent.generate_plan(
                    resolved_query,
                    context={
                        "metadata": req.metadata,
                        "adaptive_profile": adaptive_profile,
                        "data_source_context": data_source_context,
                        "user_preference_context": req.metadata.get(
                            "user_preference_context_block", ""
                        ),
                        "conversation_summary": req.metadata.get("conversation_summary", ""),
                        "grounded_entities": [
                            {
                                "original_term": g.original_term,
                                "entity_type": g.entity_type,
                                "canonical_name": g.canonical_name,
                                "mappings": g.mappings,
                                "confidence": g.confidence,
                            }
                            for g in grounded_entities
                        ],
                        "conversation_history": req.history,
                        "conversation_state": conv_state_dict,
                        "dialogue_state": (
                            {
                                "active_domain": dialogue_state.active_domain,
                                "referenced_previous_result": dialogue_state.referenced_previous_result,
                                "referenced_agent_type": dialogue_state.referenced_agent_type,
                                "resolved_query": dialogue_state.resolved_query,
                            }
                            if dialogue_state and dialogue_state.referenced_previous_result
                            else None
                        ),
                        "reference_result": (
                            {
                                "turn_type": reference_result.turn_type,
                                "resolved_query": reference_result.resolved_query,
                                "confidence": reference_result.confidence,
                                "corrected_constraints": reference_result.corrected_constraints,
                                "suggested_domain": reference_result.suggested_domain,
                                "suggested_agent": reference_result.suggested_agent,
                            }
                            if reference_result and reference_result.confidence >= 0.5
                            else None
                        ),
                    },
                )

        # ── XAI trace: record plan decision ──────────────────────────
        if xai_tracer and xai_trace_id:
            try:
                xai_tracer.record_decision(
                    xai_trace_id,
                    "PLAN",
                    "plan_generated",
                    {"subtask_count": len(plan.subtasks), "merge_strategy": plan.merge_strategy},
                    f"Generated {len(plan.subtasks)} subtasks with {plan.merge_strategy} merge",
                )
            except Exception:
                pass

        # Hard-guard: auto-inject subtasks only when NOT in force_mode
        q_lower = (req.query or "").lower()
        if not force_mode:
            doc_intent = any(
                k in q_lower
                for k in [
                    "文档",
                    "读取",
                    "总结",
                    "归纳",
                    "附件",
                    "根据文档",
                    "从文档",
                    ".pdf",
                    ".doc",
                    ".docx",
                    ".txt",
                    ".md",
                    "pdf",
                    "docx",
                ]
            )
            has_rag = any(s.agent_type == "rag" for s in plan.subtasks)
            if doc_intent and not has_rag and bool(settings.kernel_agent_rag_enabled):
                from kernel.plan_agent import SubTask

                plan.subtasks.append(
                    SubTask(
                        agent_type="rag",
                        query=req.query,
                        params={
                            "top_k": 8,
                            "sources": ["documents", "semantic_memory"],
                            "min_score": adaptive_profile["rag_min_score"],
                        },
                    )
                )

            data_intent = any(
                k in q_lower
                for k in [
                    "数据库",
                    "数据表",
                    "表",
                    "sql",
                    "查询",
                    "统计",
                    "报表",
                    "销量",
                    "订单",
                    "分析",
                    "图表",
                    "字段",
                    "列",
                    "聚合",
                    "分组",
                    "近",
                    "最近",
                    "最新",
                    "总数",
                    "条数",
                    "金额",
                    "收入",
                ]
            )
            has_data = any(s.agent_type == "data" for s in plan.subtasks)
            if data_intent and not has_data and data_source_context.get("data_source_id"):
                from kernel.plan_agent import SubTask

                plan.subtasks.append(
                    SubTask(
                        agent_type="data",
                        query=req.query,
                        params={"data_source_id": data_source_context["data_source_id"]},
                    )
                )
            elif data_intent and data_source_context.get("data_source_id"):
                for s in plan.subtasks:
                    if s.agent_type == "data":
                        p = dict(s.params or {})
                        p.setdefault("data_source_id", data_source_context["data_source_id"])
                        s.params = p

        # inject runtime context for agents that require session/user binding
        patched_subtasks = []
        for s in plan.subtasks:
            p = dict(s.params or {})
            p.setdefault("session_id", req.session_id)
            p.setdefault("user_id", req.user_id)
            if s.agent_type == "rag":
                p.setdefault("min_score", adaptive_profile["rag_min_score"])
            patched_subtasks.append(type(s)(agent_type=s.agent_type, query=s.query, params=p))
        plan.subtasks = [s for s in patched_subtasks if self.registry.has_agent(s.agent_type)]
        plan.adaptive_profile = adaptive_profile
        if bool(settings.kernel_agent_dag_scheduling_enabled):
            for idx, s in enumerate(plan.subtasks):
                if idx > 0 and not s.depends_on and s.agent_type in {"rag", "web"}:
                    s.depends_on = [f"node_{idx-1}_{plan.subtasks[idx-1].agent_type}"]
        plan.max_parallel = min(max(1, plan.max_parallel), self.max_parallel)

        # ── Correction dispatch: only run replaced subtasks, merge with reused ──
        if correction_plan is not None and correction_replaced_indices:
            from kernel.plan_agent import TaskPlan as TP

            # Build a mini-plan with only the replaced subtasks
            replaced_subtasks = [
                plan.subtasks[i]
                for i in correction_replaced_indices
                if i < len(plan.subtasks)
            ]
            if replaced_subtasks:
                mini_plan = TP(
                    subtasks=replaced_subtasks,
                    merge_strategy=plan.merge_strategy,
                    max_parallel=plan.max_parallel,
                )
                new_results = (
                    await self.dispatcher.dispatch(mini_plan, event_cb=event_cb)
                    if mini_plan.subtasks
                    else []
                )
                # Merge: new results fill at replaced indices, rest from reused
                agent_results = []
                for i in range(len(plan.subtasks)):
                    if i in correction_replaced_indices:
                        repl_idx = correction_replaced_indices.index(i)
                        if repl_idx < len(new_results):
                            agent_results.append(new_results[repl_idx])
                        else:
                            agent_results.append(
                                correction_reused.get(
                                    i,
                                    AgentResult(
                                        task_id="",
                                        agent_type=plan.subtasks[i].agent_type
                                        if i < len(plan.subtasks)
                                        else "",
                                        status="error",
                                        content="",
                                        error="correction dispatch: no result",
                                    ),
                                )
                            )
                    else:
                        reused = correction_reused.get(i)
                        if reused is not None:
                            agent_results.append(reused)
                        else:
                            agent_results.append(
                                AgentResult(
                                    task_id="",
                                    agent_type=plan.subtasks[i].agent_type
                                    if i < len(plan.subtasks)
                                    else "",
                                    status="error",
                                    content="",
                                    error="missing reused result",
                                )
                            )
            else:
                agent_results = []
        else:
            agent_results = (
                await self.dispatcher.dispatch(plan, event_cb=event_cb) if plan.subtasks else []
            )
        dispatch_span = tctx.start_span("dispatch", parent_span_id=root_span) if tctx else ""
        if trace_id:
            await cognitive_event_bus.publish(
                cognitive_event_bus.emit_execution(
                    trace_id=trace_id,
                    span_id=dispatch_span,
                    parent_span_id=root_span,
                    payload={
                        "action": "orchestrator.dispatch.completed",
                        "subtasks": [
                            {"agent_type": s.agent_type, "query": s.query, "params": s.params}
                            for s in plan.subtasks
                        ],
                        "result_count": len(agent_results),
                    },
                    session_id=req.session_id,
                    user_id=req.user_id,
                    source="orchestrator_v4",
                )
            )
        for result in agent_results:
            task_model.update_from_agent_result(result.model_dump(mode="json"))

        successful = [
            r
            for r in agent_results
            if r.status == "success"
            and ((r.metadata and bool(r.metadata)) or (r.content or "").strip())
        ]

        # If evidence quality is low (especially rag/data/tool weak or empty), we may replan.
        # But never let web fallback override explicit internal knowledge / database questions.
        low_quality = False
        rag_results = [r for r in agent_results if r.agent_type == "rag"]
        if rag_results:
            chunks = []
            rag_quality_metadata = []
            for rr in rag_results:
                if isinstance(rr.metadata, dict):
                    c = rr.metadata.get("chunks")
                    if isinstance(c, list):
                        chunks.extend(c)
                    # Extract quality metrics
                    quality = rr.metadata.get("quality")
                    if isinstance(quality, dict):
                        rag_quality_metadata.append(quality)
            if len(chunks) == 0:
                low_quality = True
            else:
                # Check RAG quality scores
                RAG_QUALITY_THRESHOLD = 0.5  # Configurable threshold
                avg_scores = [
                    q.get("avg_score", 0.0)
                    for q in rag_quality_metadata
                    if isinstance(q.get("avg_score"), (int, float))
                ]
                sufficient_flags = [
                    q.get("sufficient", False)
                    for q in rag_quality_metadata
                    if isinstance(q.get("sufficient"), bool)
                ]

                rag_quality_low = False
                rag_improvement_attempted = False
                if avg_scores:
                    avg_score = sum(avg_scores) / len(avg_scores)
                    if avg_score < RAG_QUALITY_THRESHOLD:
                        rag_quality_low = True
                elif sufficient_flags and not any(sufficient_flags):
                    rag_quality_low = True

                if rag_quality_low and not rag_improvement_attempted:
                    rag_improvement_attempted = True
                    # Attempt query rewriting and re-run RAG
                    query_rewriter = QueryRewriter()
                    improved_query = await query_rewriter.rewrite_with_rag_context(
                        original_query=req.query,
                        rag_chunks=chunks[:10],  # limit to top chunks
                    )
                    if improved_query and improved_query != req.query:
                        from kernel.plan_agent import SubTask, TaskPlan

                        # Create new RAG subtask with improved query
                        extra_rag = SubTask(
                            agent_type="rag",
                            query=improved_query,
                            params={
                                "session_id": req.session_id,
                                "user_id": req.user_id,
                                "top_k": 8,
                                "sources": ["documents", "semantic_memory"],
                                "min_score": adaptive_profile["rag_min_score"],
                            },
                        )
                        extra_result = await self.dispatcher.dispatch(
                            TaskPlan(subtasks=[extra_rag], max_parallel=1)
                        )
                        if extra_result:
                            agent_results.extend(extra_result)
                            for result in extra_result:
                                task_model.update_from_agent_result(result.model_dump(mode="json"))
                            # Recompute successful list with updated agent_results
                            successful = [
                                r
                                for r in agent_results
                                if r.status == "success"
                                and ((r.metadata and bool(r.metadata)) or (r.content or "").strip())
                            ]
                            # Update rag_results and chunks with new results
                            new_rag_results = [r for r in extra_result if r.agent_type == "rag"]
                            rag_results.extend(new_rag_results)
                            for rr in new_rag_results:
                                if isinstance(rr.metadata, dict):
                                    c = rr.metadata.get("chunks")
                                    if isinstance(c, list):
                                        chunks.extend(c)
                                    q = rr.metadata.get("quality")
                                    if isinstance(q, dict):
                                        rag_quality_metadata.append(q)
                            # Re-evaluate quality after improvement
                            avg_scores = [
                                q.get("avg_score", 0.0)
                                for q in rag_quality_metadata
                                if isinstance(q.get("avg_score"), (int, float))
                            ]
                            sufficient_flags = [
                                q.get("sufficient", False)
                                for q in rag_quality_metadata
                                if isinstance(q.get("sufficient"), bool)
                            ]
                            if avg_scores:
                                avg_score = sum(avg_scores) / len(avg_scores)
                                if avg_score >= RAG_QUALITY_THRESHOLD:
                                    rag_quality_low = False
                            elif sufficient_flags and any(sufficient_flags):
                                rag_quality_low = False

                # If RAG quality still low after improvement attempt, mark low_quality
                if rag_quality_low:
                    low_quality = True

        if any(r.agent_type in {"data", "tool"} and r.status != "success" for r in agent_results):
            low_quality = True
            task_model.add_hypothesis(
                "部分关键子任务失败，原始假设可能不成立", confidence=0.45, source="agent_result"
            )

        replan_triggered = False
        has_web = any(s.agent_type == "web" for s in plan.subtasks)
        explicit_internal_intent = (
            bool(force_mode)
            or any(
                k in q_lower
                for k in [
                    "文档",
                    "手册",
                    "知识库",
                    "项目内",
                    "系统内",
                    "本项目",
                    "内部",
                    "代码",
                    "配置",
                    "规则",
                    "说明",
                    "根据文档",
                    "从文档",
                    "总结",
                    "归纳",
                    "读取",
                    "读取本地",
                    "附件",
                    ".pdf",
                    ".doc",
                    ".docx",
                    ".txt",
                    ".md",
                ]
            )
            or bool(data_source_context.get("data_source_id"))
        )
        if (
            low_quality
            and bool(settings.kernel_agent_web_enabled)
            and not has_web
            and not explicit_internal_intent
        ):
            from kernel.plan_agent import SubTask, TaskPlan

            replan_triggered = True
            # 最小重规划：先补一个 web 子任务；避免完整重跑导致成本激增
            extra = SubTask(
                agent_type="web",
                query=req.query,
                params={"session_id": req.session_id, "user_id": req.user_id},
            )
            extra_result = await self.dispatcher.dispatch(
                TaskPlan(subtasks=[extra], max_parallel=1)
            )
            if extra_result:
                agent_results.extend(extra_result)
                for result in extra_result:
                    task_model.update_from_agent_result(result.model_dump(mode="json"))
                # Recompute successful list with updated agent_results
                successful = [
                    r
                    for r in agent_results
                    if r.status == "success"
                    and ((r.metadata and bool(r.metadata)) or (r.content or "").strip())
                ]

        if not successful and not any(r.status == "success" for r in agent_results):
            # force_mode: return a helpful message instead of falling back to LLM
            if force_mode in ("data_query", "data_analysis"):
                fallback = (
                    "数据查询执行失败。可能原因：\n"
                    "- 数据源未配置或连接失败，请先在「数据源」页面添加并测试连接。\n"
                    "- 查询中涉及的表或字段在数据源中不存在，请检查字段名称。\n"
                    "- 查询未返回有效结果，可尝试简化查询条件。"
                )
            elif force_mode == "rag":
                fallback = (
                    f"未在知识库中找到与「{req.query}」相关的内容。\n"
                    "请先在「知识库」页面上传相关文档（PDF、TXT、MD 等），上传完成后重新查询。"
                )
            elif force_mode == "anomaly_tracking":
                fallback = "当前没有可用的技能。请在「技能」页面创建或安装技能后重试。"
            elif force_mode in ("product", "rule_engine"):
                fallback = (
                    f"未找到与「{req.query}」匹配的产品规则。\n"
                    "请确认查询内容是否在已配置的产品规则范围内，或在 rules/ 目录下添加新规则。"
                )
            elif force_mode == "tool":
                tool_err_msg = (agent_results[0].error if agent_results else "") or "工具执行失败"
                fallback = (
                    f"工具调用失败：{tool_err_msg}\n"
                    "可能原因：\n"
                    "- 天气查询需要配置 WEATHER_API_KEY 环境变量\n"
                    "- 时间查询需要系统时间可用\n"
                    "- 计算器需要提供合法的数学表达式\n"
                    "如需联网搜索实时信息，请尝试使用 /web 模式。"
                )
            else:
                fallback = await self._llm_fallback_answer(
                    req, memory_context=req.metadata.get("memory_context")
                )

            elapsed_ms = int((monotonic() - t0) * 1000)
            bus_used = [
                {"agent_type": s.agent_type, "query": s.query}
                for s in plan.subtasks
                if bool(settings.kernel_agent_bus_enabled)
            ]
            fallback = self._sanitize_user_output(fallback)
            metrics = {
                "first_token_ms": elapsed_ms,
                "orchestrator_latency_ms": elapsed_ms,
                "supervisor_retry_count": 0,
                "agent_count": len(agent_results),
                "avg_agent_latency_ms": int(elapsed_ms / max(1, len(agent_results))),
            }
            runtime_metrics_store.record(metrics)
            return OrchestratorV4Response(
                content=fallback,
                route=(
                    "force_mode_error"
                    if force_mode in ("data_query", "data_analysis", "rag", "anomaly_tracking")
                    else "fallback_llm"
                ),
                strategy="degraded",
                passed_validation=True,
                validation_score=0.8,
                hallucination_risk=0.1,
                intent_category=force_mode or "general",
                metadata={
                    "orchestrator_version": "v4",
                    "adaptive_profile": adaptive_profile,
                    "force_mode": force_mode,
                    "bus_enabled": bool(settings.kernel_agent_bus_enabled),
                    "bus_mode_used_tasks": bus_used,
                    "plan": {
                        "adaptive_profile": adaptive_profile,
                        "subtasks": [
                            {"agent_type": s.agent_type, "query": s.query, "params": s.params}
                            for s in plan.subtasks
                        ],
                        "merge_strategy": plan.merge_strategy,
                        "max_parallel": plan.max_parallel,
                    },
                    "agent_results": [r.model_dump(mode="json") for r in agent_results],
                    "fusion": {"confidence": 0.8, "conflicts": [], "context": fallback},
                    "critic": {"feedback": "fallback_llm"},
                    "execution_graph": {"nodes": [], "edges": [], "state": {"fallback_llm": True}},
                    "metrics": metrics,
                },
            )

        tool_results: list[ToolResult] = []
        for r in agent_results:
            if r.agent_type == "data":
                source = "sql"
            elif r.agent_type == "web":
                source = "web_search"
            elif r.agent_type == "rag":
                source = "document"
            else:
                source = "tool"
            if r.agent_type == "data":
                payload = r.metadata if r.metadata else r.content
            elif r.agent_type == "rag":
                chunks = (r.metadata or {}).get("chunks") if isinstance(r.metadata, dict) else None
                llmwiki_entries = (
                    (r.metadata or {}).get("llmwiki_entries")
                    if isinstance(r.metadata, dict)
                    else None
                )
                vector_chunks = (
                    (r.metadata or {}).get("vector_chunks")
                    if isinstance(r.metadata, dict)
                    else None
                )
                if isinstance(llmwiki_entries, list) and llmwiki_entries:
                    wiki_payload = "\n".join(
                        f"[{i+1}] {str(c.get('question') or c.get('title') or 'LLMWiki')}：{str(c.get('answer') or c.get('text') or '')[:220]}"
                        for i, c in enumerate(llmwiki_entries[:3])
                        if isinstance(c, dict)
                    )
                    tool_results.append(
                        ToolResult(
                            source="llmwiki",
                            data=wiki_payload,
                            confidence=min(0.98, r.confidence + 0.08),
                            source_priority=1,
                        )
                    )
                if isinstance(vector_chunks, list) and vector_chunks:
                    payload = "\n".join(
                        f"[{i+1}] {str(c.get('title') or c.get('id') or '证据')}：{str(c.get('text') or '')[:220]}"
                        for i, c in enumerate(vector_chunks[:5])
                        if isinstance(c, dict)
                    )
                    tool_results.append(
                        ToolResult(
                            source="document",
                            data=payload,
                            confidence=r.confidence,
                            source_priority=2,
                        )
                    )
                    continue
                if isinstance(chunks, list) and chunks:
                    payload = "\n".join(
                        f"[{i+1}] {str(c.get('title') or c.get('id') or '证据')}：{str(c.get('text') or '')[:220]}"
                        for i, c in enumerate(chunks[:5])
                        if isinstance(c, dict)
                    )
                    tool_results.append(
                        ToolResult(source=source, data=payload, confidence=r.confidence)
                    )
                # Skip creating document ToolResult when no chunks found
                continue
            else:
                payload = (
                    r.content if (r.content or "").strip() else (r.metadata if r.metadata else "")
                )
            tool_results.append(ToolResult(source=source, data=payload, confidence=r.confidence))

        # ── Inject memory context as additional fusion source ──────────
        memory_context = req.metadata.get("memory_context", [])
        if memory_context:
            for mc in memory_context:
                if isinstance(mc, dict) and mc.get("content"):
                    tool_results.append(
                        ToolResult(
                            source="memory",
                            data=str(mc["content"])[:500],
                            confidence=float(mc.get("score", 0.5)),
                            source_priority=3,
                        )
                    )
        # ── End memory context injection ────────────────────────────────

        # ── Inject attachment context as additional fusion source ──────
        attachment_contexts = req.metadata.get("attachment_contexts", [])
        if attachment_contexts:
            for ac in attachment_contexts:
                if isinstance(ac, dict) and ac.get("content"):
                    tool_results.append(
                        ToolResult(
                            source="attachment",
                            data=str(ac["content"])[:4000],
                            confidence=0.85,
                            source_priority=3,
                        )
                    )
        # ── End attachment context injection ───────────────────────────

        # ── Build background_materials from attachment contexts ─────────
        attachment_contexts_for_answer = req.metadata.get("attachment_contexts", [])
        background_materials = ""
        if attachment_contexts_for_answer:
            bg_parts = [
                str(ac["content"])
                for ac in attachment_contexts_for_answer
                if isinstance(ac, dict) and ac.get("content")
            ]
            if bg_parts:
                background_materials = "\n\n---\n\n".join(bg_parts)
        # ── End background_materials ─────────────────────────────────────

        fusion = self.fusion_engine.run(
            FusionInput(
                query=req.query,
                results=tool_results,
                adaptive_profile=adaptive_profile,
                conversation_history=req.history,
            )
        )

        # ── XAI trace: record fusion ──────────────────────────────────
        if xai_tracer and xai_trace_id:
            try:
                xai_tracer.record_fusion(
                    xai_trace_id,
                    source_count=len(tool_results),
                    merged_length=len(fusion.merged_context or ""),
                    strategy=getattr(plan, "merge_strategy", "direct"),
                )
            except Exception:
                pass

        fusion_span = tctx.start_span("fusion", parent_span_id=root_span) if tctx else ""
        if trace_id:
            await cognitive_event_bus.publish(
                cognitive_event_bus.emit_fusion(
                    trace_id=trace_id,
                    span_id=fusion_span,
                    parent_span_id=root_span,
                    payload={
                        "action": "orchestrator.fusion.completed",
                        "confidence": fusion.confidence,
                        "conflicts": fusion.conflicts,
                        "evidence_count": len(tool_results),
                    },
                    session_id=req.session_id,
                    user_id=req.user_id,
                    source="orchestrator_v4",
                )
            )

        answer_draft = ""
        first_token_ms = 0
        # Skip draft when attachment contexts are present — the draft shows
        # raw agent results (e.g. database rows) that are confusing before
        # the LLM has had a chance to synthesize a proper answer from the
        # attachment content.
        _has_attachment = any(r.source == "attachment" for r in tool_results)
        if not _has_attachment:
            draft_threshold = float(adaptive_profile["draft_threshold"])
            draft_max_chars = max(60, int(adaptive_profile["draft_max_chars"]))
            if fusion.confidence >= draft_threshold and (fusion.merged_context or "").strip():
                raw_draft = self._sanitize_user_output(
                    (fusion.merged_context or "")[:draft_max_chars]
                )
                if raw_draft:
                    answer_draft = f"以下是目前梳理出的关键信息：\n\n{raw_draft}"
                first_token_ms = int((monotonic() - t0) * 1000)

        annotated_results = []
        for r in agent_results:
            annotated_results.append(
                self.annotator.annotate_agent_result(
                    content=str(r.content or ""),
                    agent_type=r.agent_type,
                    metadata=r.metadata or {},
                    citations=(
                        (r.metadata or {}).get("citations", [])
                        if isinstance(r.metadata, dict)
                        else []
                    ),
                )
            )
        merged_annotated = self.annotator.merge_responses(annotated_results)

        has_document = any(r.source in {"document", "llmwiki"} for r in tool_results)
        # Count actual RAG chunks (not just presence of document source)
        rag_chunks_count = 0
        rag_citations = []
        if has_document:
            for r in agent_results:
                if r.agent_type != "rag" or not isinstance(r.metadata, dict):
                    continue
                chunks = r.metadata.get("chunks")
                if isinstance(chunks, list):
                    rag_chunks_count += len(chunks)
                cits = r.metadata.get("citations")
                if isinstance(cits, list):
                    rag_citations.extend([c for c in cits if isinstance(c, dict)])

        # Only enter RAG answer path when we actually have document evidence
        if has_document and rag_chunks_count > 0:
            grounded = await self._llm_grounded_answer(
                req.query,
                fusion.merged_context or "",
                history=req.history,
                background_materials=background_materials,
                user_style_hints=user_style_hints,
            )
            answer = self._sanitize_user_output(grounded or (fusion.merged_context or ""))

            answer = self._format_rag_answer(answer, rag_chunks_count, rag_citations)
        elif has_document and rag_chunks_count == 0 and force_mode == "rag":
            # Explicit force_mode="rag" but no documents found — tell the user directly
            answer = f"我在知识库中仔细搜索了一下，但没有找到与「{req.query}」直接相关的文档。建议试试上传相关文档，或者切换到其他查询模式再试。"
        elif not has_document and force_mode == "rag":
            # force_mode="rag" but user has no documents at all — return RAG agent's helpful message
            rag_result = next((r for r in agent_results if r.agent_type == "rag"), None)
            answer = (
                (rag_result.content or "").strip()
                if rag_result and rag_result.status == "success"
                else ""
            )
            if not answer:
                answer = (
                    "当前账户下暂未上传任何文档。请先在「文档」页面上传知识库文档"
                    "（PDF/DOCX/TXT/MD 等格式），上传后即可使用 /rag 模式进行文档检索与问答。\n\n"
                    "如果不需要检索文档，可以使用 /web 联网搜索，或直接输入问题进行通用问答。"
                )
        else:
            answer = ""
            has_data = any(r.agent_type == "data" and r.status == "success" for r in agent_results)
            has_data_error = any(
                r.agent_type == "data" and r.status == "error" for r in agent_results
            )
            # When attachments are present and the user did not explicitly request
            # data query/analysis, skip the raw data-answer so that the LLM-grounded
            # path below can synthesise a proper answer from all sources (attachment
            # content + data results + web/tool results).
            _data_mode = force_mode in {"data_query", "data_analysis"}
            if has_data and (not _has_attachment or _data_mode):
                answer = self._format_data_answer(req.query, agent_results)
            if not answer and has_data_error and force_mode in {"data_query", "data_analysis"}:
                # force_mode data agent failed — return helpful message instead of falling back
                error_detail = ""
                for r in agent_results:
                    if r.agent_type == "data" and r.status == "error" and (r.error or "").strip():
                        error_detail = f"\n\n错误详情：{r.error}"
                        break
                answer = (
                    "数据查询没能成功执行，可能的原因是：\n"
                    "- 数据源还没有配置好或者连接断开了，可以先在「数据源」页面确认一下连接状态\n"
                    "- 查询用到的表或字段在数据源中不存在，检查一下数据源的表结构是否正确\n"
                    "- 查询条件比较复杂，试试简化条件或直接指定表名和字段名"
                    f"{error_detail}"
                )
            if not answer:
                has_web = any(r.source == "web_search" for r in tool_results)
                has_meaningful_tool = any(
                    r.source == "tool" and r.data and len(str(r.data)) > 80 for r in tool_results
                )
                if (has_web or has_meaningful_tool or _has_attachment) and (
                    fusion.merged_context or ""
                ).strip():
                    grounded = await self._llm_grounded_answer(
                        req.query,
                        fusion.merged_context or "",
                        history=req.history,
                        background_materials=background_materials,
                        user_style_hints=user_style_hints,
                    )
                    answer = self._sanitize_user_output(grounded or (fusion.merged_context or ""))
                else:
                    merged_annotated.fragments = [
                        f for f in merged_annotated.fragments if (f.text or "").strip()
                    ]
                    answer = self._sanitize_user_output(
                        merged_annotated.to_text()
                        if merged_annotated.fragments
                        else (fusion.merged_context or "")
                    )

        conflict_annotation = None
        if (
            str(adaptive_profile.get("name", "balanced") or "balanced") == "quality"
            and fusion.conflicts
        ):
            conflict_annotation = {
                "mode": "quality_disagreement",
                "summary": "当前证据存在接近分歧，保留主答案与备选证据供前端展示。",
                "conflicts": fusion.conflicts[:3],
                "alternates": fusion.alternate_contexts[:3],
                "evidence_map": fusion.evidence_map[:6],
            }
            alt_lines = ["\n\n分歧说明："]
            alt_lines.extend([f"- {c}" for c in fusion.conflicts[:3]])
            if fusion.alternate_contexts:
                alt_lines.append("\n其他候选证据：")
                alt_lines.extend([f"- {a}" for a in fusion.alternate_contexts[:3]])
            if "分歧说明" not in answer:
                answer = f"{answer}{''.join(alt_lines)}".strip()

        validated = self.annotator.annotate_model_response(answer, context_sources=[])
        is_valid, issues, validated_resp = self.validator.validate_response(validated)
        validated_text = self._sanitize_user_output(validated_resp.to_text())
        if not validated_text:
            validated_text = self._sanitize_user_output(
                answer or fusion.merged_context or answer_draft
            )
        if not validated_text:
            validated_text = "我已经完成了分析，但手头的信息还不足以给出一个完整回答。方便的话，补充一些细节或换个角度描述问题，我能帮得更到位。"
        answer = validated_text

        graph_nodes = []
        graph_edges = []
        # 将代理结果映射到子任务（假设顺序相同）
        for i, s in enumerate(plan.subtasks):
            node_id = f"agent_{i}_{s.agent_type}"
            result_status = "SUCCESS"
            result_output = {}
            if i < len(agent_results):
                r = agent_results[i]
                result_status = "SUCCESS" if r.status == "success" else "ERROR"
                result_output = r.metadata if r.metadata else {}
            graph_nodes.append(
                {
                    "id": node_id,
                    "type": "agent_call",
                    "stage": "AGENT",
                    "status": result_status,
                    "metadata": {"agent_type": s.agent_type, "query": s.query, "params": s.params},
                    "output": result_output,
                }
            )
            if i > 0:
                graph_edges.append({"source": graph_nodes[i - 1]["id"], "target": node_id})

        # Build candidate answers from agent results
        candidate_answers: list[dict[str, Any]] = []
        for r in agent_results:
            if r.status == "success" and r.content and len(str(r.content)) > 30:
                candidate_answers.append({
                    "answer": str(r.content)[:1000],
                    "source": getattr(r, "agent_type", "unknown"),
                })

        critique = self.critic_engine.run(
            CriticInput(
                query=req.query,
                answer=answer,
                fusion_context=fusion.merged_context,
                fusion_confidence=fusion.confidence,
                adaptive_profile=adaptive_profile,
                candidate_answers=candidate_answers,
            )
        )
        critic_span = tctx.start_span("critic", parent_span_id=root_span) if tctx else ""
        if trace_id:
            await cognitive_event_bus.publish(
                cognitive_event_bus.emit_critic(
                    trace_id=trace_id,
                    span_id=critic_span,
                    parent_span_id=root_span,
                    payload={
                        "action": "orchestrator.critic.completed",
                        "need_fix": critique.need_fix,
                        "feedback": critique.feedback,
                        "epistemic_issues": issues,
                    },
                    session_id=req.session_id,
                    user_id=req.user_id,
                    source="orchestrator_v4",
                )
            )

        # ── XAI trace: record critic ─────────────────────────────────
        if xai_tracer and xai_trace_id:
            try:
                xai_tracer.record_critic(
                    xai_trace_id,
                    issues_found=len(issues),
                    corrections=[critique.feedback] if critique.need_fix else [],
                )
            except Exception:
                pass

        if critique.need_fix:
            task_model.add_hypothesis(
                "Critic 判定需修正，切换到改进答案路径", confidence=0.6, source="critic"
            )
            answer = critique.improved_answer or answer
        if not (answer or "").strip():
            answer = self._sanitize_user_output(fusion.merged_context or answer_draft)
        if not (answer or "").strip():
            answer = "我已经完成了分析，但手头的信息还不足以给出一个完整回答。方便的话，补充一些细节或换个角度描述问题，我能帮得更到位。"

        # ── ClarificationGate: check if answer needs follow-up ─────────
        clarification_result = None
        clarification_data: dict[str, Any] | None = None
        try:
            gate = ClarificationGate()
            clarification_result = await gate.check(
                fusion_confidence=fusion.confidence,
                answer=answer,
                query=req.query,
            )
            if clarification_result is not None and clarification_result.needs_clarification:
                q = clarification_result.question
                if q:
                    # Build structured clarification data for frontend rendering
                    clarification_data = {
                        "question_id": q.question_id,
                        "question_text": q.question_text,
                        "missing_entities": q.missing_entities,
                        "suggested_options": q.suggested_options,
                    }

                    # When confidence is critically low, replace answer with
                    # the clarification question instead of appending weak answer
                    if fusion.confidence < 0.4:
                        answer = q.question_text
                        if q.suggested_options:
                            answer += "\n\n你可以参考以下方向补充信息：\n"
                            for i, opt in enumerate(q.suggested_options[:3], 1):
                                answer += f"{i}. {opt}\n"
                    else:
                        # Moderate confidence: give answer but flag uncertainty
                        clarify_suffix = "\n\n---\n\n"
                        clarify_suffix += f"💡 {q.question_text}"
                        if q.suggested_options:
                            clarify_suffix += "\n\n你可以参考以下方向补充信息：\n"
                            for i, opt in enumerate(q.suggested_options[:3], 1):
                                clarify_suffix += f"{i}. {opt}\n"
                        answer = f"{answer}{clarify_suffix}"
        except Exception:
            clarification_result = None
            clarification_data = None

        # ── Inject tool card JSON for frontend card rendering ──────────
        for r in agent_results:
            if r.agent_type != "tool" or r.status != "success":
                continue
            payload = (r.metadata or {}).get("payload") if isinstance(r.metadata, dict) else None
            if not isinstance(payload, dict):
                continue
            payload_type = str(payload.get("type", ""))
            if payload_type in ("time", "weather"):
                card_json = json.dumps(payload, ensure_ascii=False)
                answer = f"```json\n{card_json}\n```\n\n{answer}"
        # ── End tool card injection ─────────────────────────────────────

        bus_used = [
            {"agent_type": s.agent_type, "query": s.query}
            for s in plan.subtasks
            if bool(settings.kernel_agent_bus_enabled)
        ]
        supervisor_retry_count = sum(
            1
            for r in agent_results
            if isinstance(r.metadata, dict)
            and isinstance(r.metadata.get("runtime_supervisor"), dict)
            and int((r.metadata.get("runtime_supervisor") or {}).get("attempt", 0) or 0) > 0
        )
        total_latency_ms = int((monotonic() - t0) * 1000)
        if first_token_ms <= 0:
            first_token_ms = total_latency_ms

        metrics = {
            "first_token_ms": first_token_ms,
            "orchestrator_latency_ms": total_latency_ms,
            "supervisor_retry_count": supervisor_retry_count,
            "agent_count": len(agent_results),
            "avg_agent_latency_ms": int(total_latency_ms / max(1, len(agent_results))),
        }
        runtime_metrics_store.record(metrics)
        final_span = tctx.start_span("final", parent_span_id=root_span) if tctx else ""
        if trace_id:
            await cognitive_event_bus.publish(
                cognitive_event_bus.emit_learning(
                    trace_id=trace_id,
                    span_id=final_span,
                    parent_span_id=root_span,
                    payload={
                        "action": "orchestrator.process.completed",
                        "route": "agent_cluster",
                        "validation_score": max(0.6, fusion.confidence),
                        "passed_validation": True,
                        "agent_count": len(agent_results),
                        "supervisor_retry_count": supervisor_retry_count,
                    },
                    session_id=req.session_id,
                    user_id=req.user_id,
                    source="orchestrator_v4",
                )
            )

        # ── Build state_patch for next turn ────────────────────────────
        state_patch: dict[str, Any] = {
            "last_user_goal": req.query,
            "last_assistant_summary": (answer or "")[:300],
            "last_plan": {
                "subtasks": [
                    {
                        "agent_type": s.agent_type,
                        "query": s.query,
                        "params": s.params,
                    }
                    for s in plan.subtasks
                ],
                "merge_strategy": plan.merge_strategy,
                "max_parallel": plan.max_parallel,
            },
            "last_results": [
                {
                    "agent_type": r.agent_type,
                    "status": r.status,
                    "content": (r.content or "")[:300],
                    "result_refs": [
                        {
                            "ref_id": ref.ref_id,
                            "type": ref.type,
                            "title": ref.title,
                            "summary": ref.summary,
                        }
                        for ref in ResultRefBuilder.build_from_agent_result(
                            r,
                            plan.subtasks[i].query if i < len(plan.subtasks) else "",
                        )
                    ],
                }
                for i, r in enumerate(agent_results)
            ],
        }
        if agent_results:
            all_result_refs = ResultRefBuilder.build_from_task_results(
                agent_results, plan.subtasks
            )
            state_patch["last_result_refs"] = all_result_refs

        # Persist conversation summary from ContextAssembler
        conversation_summary = req.metadata.get("conversation_summary", "")
        if conversation_summary:
            state_patch["conversation_summary"] = conversation_summary

        if reference_result is not None and reference_result.confidence >= 0.5:
            state_patch["last_turn_type"] = reference_result.turn_type
            if reference_result.corrected_constraints:
                state_patch["active_constraints"] = reference_result.corrected_constraints
        if clarification_result is not None and clarification_result.needs_clarification:
            question = clarification_result.question
            state_patch["pending_clarification"] = {
                "question_id": question.question_id if question else "",
                "question_text": question.question_text if question else "",
                "missing_entities": question.missing_entities if question else [],
                "suggested_options": question.suggested_options if question else [],
            }
        elif (
            req.metadata.get("clarify_question_id")
            or (conv_state_dict and conv_state_dict.get("pending_clarification"))
        ):
            state_patch["pending_clarification"] = None

        # ── Collect result_refs from agent results ─────────────────────
        all_result_refs: list[dict[str, Any]] = []
        for r in agent_results:
            if isinstance(r.metadata, dict):
                refs = r.metadata.get("result_refs", [])
                if isinstance(refs, list):
                    all_result_refs.extend(refs)

        # ── XAI trace: record final and finish trace ───────────────────
        if xai_tracer and xai_trace_id:
            try:
                xai_tracer.record_final(
                    xai_trace_id,
                    answer_length=len(answer or ""),
                    confidence=fusion.confidence,
                    total_agents=len(agent_results),
                    total_latency_ms=int((monotonic() - t0) * 1000),
                )
                xai_tracer.finish_trace(xai_trace_id, {"route": "agent_cluster", "validation_score": max(0.6, fusion.confidence)})
            except Exception:
                pass

        return OrchestratorV4Response(
            content=answer,
            state_patch=state_patch if state_patch else None,
            result_refs=all_result_refs,
            route="agent_cluster",
            strategy="parallel",
            passed_validation=True,
            validation_score=max(0.6, fusion.confidence),
            hallucination_risk=0.0,
            intent_category="agent_cluster",
            metadata={
                "orchestrator_version": "v4",
                "adaptive_profile": adaptive_profile,
                "bus_enabled": bool(settings.kernel_agent_bus_enabled),
                "bus_mode_used_tasks": bus_used,
                "clarification": clarification_data,
                "plan": {
                    "adaptive_profile": adaptive_profile,
                    "subtasks": [
                        {"agent_type": s.agent_type, "query": s.query, "params": s.params}
                        for s in plan.subtasks
                    ],
                    "merge_strategy": plan.merge_strategy,
                    "max_parallel": plan.max_parallel,
                },
                "agent_results": [r.model_dump(mode="json") for r in agent_results],
                "fusion": {
                    "confidence": fusion.confidence,
                    "conflicts": fusion.conflicts,
                    "context": fusion.merged_context,
                },
                "answer_draft": answer_draft,
                "critic": {
                    "feedback": critique.feedback,
                    "epistemic_issues": issues,
                    "confidence_breakdown": getattr(critique, "confidence_breakdown", {}),
                    "confidence_explanation": getattr(critique, "confidence_explanation", ""),
                    "candidate_scores": (
                        [cs.to_dict() for cs in critique.candidate_scores]
                        if isinstance(getattr(critique, "candidate_scores", None), list)
                        else []
                    ),
                    "selected_candidate_index": getattr(critique, "selected_candidate_index", -1),
                },
                "metrics": metrics,
                "annotations": [
                    *(
                        [
                            {
                                "id": "conflict_summary",
                                "text": conflict_annotation["summary"],
                                "annotation": {
                                    "level": "INFO",
                                    "source_type": "fusion",
                                    "confidence": fusion.confidence,
                                    "caveats": ["quality_mode_disagreement"],
                                    "citations": [],
                                    "meta": conflict_annotation,
                                },
                            }
                        ]
                        if conflict_annotation
                        else []
                    ),
                    *[
                        {
                            "id": f.id,
                            "text": f.text,
                            "annotation": (
                                {
                                    "level": f.annotation.level.name,
                                    "source_type": f.annotation.source_type.value,
                                    "confidence": f.annotation.confidence,
                                    "caveats": f.annotation.caveats,
                                    "citations": [
                                        {
                                            "id": c.id,
                                            "source_type": c.source_type.value,
                                            "source_name": c.source_name,
                                            "snippet": c.content_snippet,
                                            "url": c.url,
                                        }
                                        for c in (f.annotation.citations if f.annotation else [])
                                    ],
                                }
                                if f.annotation
                                else None
                            ),
                        }
                        for f in validated_resp.fragments
                    ],
                ],
                "execution_graph": {
                    "nodes": graph_nodes,
                    "edges": graph_edges,
                    "state": {
                        "dynamic": True,
                        "agent_parallel": True,
                        "task_model": {
                            "open_questions": task_model.state.open_questions,
                            "confirmed_facts_count": len(task_model.state.confirmed_facts),
                            "hypotheses_count": len(task_model.state.hypotheses),
                            "replan_triggered": replan_triggered,
                        },
                    },
                },
            },
        )

    async def stream(self, req: OrchestratorV4Request) -> AsyncIterator[dict[str, Any]]:
        """Streaming variant of process() — yields events as the pipeline progresses."""
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(event)

        async def _run() -> None:
            try:
                resp = await self.process(req, event_cb=emit)
                # Emit structural metadata events
                adaptive_profile = (resp.metadata or {}).get("adaptive_profile")
                if adaptive_profile:
                    await queue.put({"type": "adaptive_profile", "data": adaptive_profile})
                force_mode = (resp.metadata or {}).get("force_mode")
                if force_mode:
                    await queue.put({"type": "force_mode", "data": {"mode": force_mode}})
                # Emit agent_start / agent_complete events from plan metadata
                for st in (resp.metadata or {}).get("plan", {}).get("subtasks", []):
                    agent_type = str(st.get("agent_type", "agent"))
                    q = str(st.get("query", ""))
                    task_id = f"{agent_type}_{abs(hash(q)) % 100000}"
                    await queue.put(
                        {
                            "type": "agent_start",
                            "data": {"agent_type": agent_type, "task_id": task_id, "query": q},
                        }
                    )
                for ar in (resp.metadata or {}).get("agent_results", []):
                    agent_type = str(ar.get("agent_type", "agent"))
                    task_id = str(ar.get("task_id", ""))
                    await queue.put(
                        {
                            "type": "agent_complete",
                            "data": {
                                "agent_type": agent_type,
                                "task_id": task_id,
                                "status": str(ar.get("status", "success")),
                                "preview": str(ar.get("content", ""))[:200],
                            },
                        }
                    )
                # Emit conflict summary if present
                for ann in (resp.metadata or {}).get("annotations", []):
                    if isinstance(ann, dict) and ann.get("id") == "conflict_summary":
                        await queue.put({"type": "conflict_summary", "data": ann})
                        break
                # Emit pipeline reasoning completion event
                plan_subtasks = (resp.metadata or {}).get("plan", {}).get("subtasks", [])
                await queue.put(
                    {
                        "type": "reasoning_step",
                        "data": {
                            "id": "v4_pipeline",
                            "stage": "STEP",
                            "content": f"已完成 {len(plan_subtasks)} 个子任务",
                            "node_id": None,
                            "status": "done",
                        },
                    }
                )
                # Emit answer draft if available
                answer_draft = str((resp.metadata or {}).get("answer_draft", "")).strip()
                if answer_draft:
                    await queue.put({"type": "answer_draft", "data": {"content": answer_draft}})
                # Emit final answer chunks
                content = (resp.content or answer_draft or "").strip()
                if not content:
                    content = (
                        "我已经完成了分析，但当前没有可直接展示的最终答案。请补充更多信息后再试。"
                    )
                if content:
                    step = 24
                    for i in range(0, len(content), step):
                        await queue.put({"type": "delta", "data": {"text": content[i : i + step]}})
                        await asyncio.sleep(0.008)
                final_data: dict[str, Any] = {
                    "content": content,
                    "route": resp.route,
                    "validation_score": resp.validation_score,
                    "passed_validation": resp.passed_validation,
                    "execution_graph": (resp.metadata or {}).get("execution_graph"),
                    "citations": (resp.metadata or {}).get("citations", []),
                    "annotations": (resp.metadata or {}).get("annotations", []),
                    "clarification": (resp.metadata or {}).get("clarification"),
                    "metadata": resp.metadata,
                    "state_patch": resp.state_patch,
                    "result_refs": resp.result_refs,
                }
                await queue.put({"type": "final_answer", "data": final_data})
            except Exception as exc:
                await queue.put({"type": "error", "data": {"message": str(exc)}})
            finally:
                await queue.put(None)

        task = asyncio.create_task(_run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        except asyncio.CancelledError:
            task.cancel()
            raise
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(Exception):
                    await task
