from __future__ import annotations

import ast
import json
import logging
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

logger = logging.getLogger(__name__)

VALID_FORCE_MODES = frozenset({"rag", "data_query", "data_analysis", "anomaly_tracking"})

from agents.data_agent import DataAgent
from agents.rag_agent import RagAgent
from agents.registry import AgentRegistry
from agents.skills_agent import SkillsAgent
from agents.web_agent import WebAgent
from execution.tool_router.router import ToolRouter
from kernel.adaptive_profiles import get_profile_defaults
from kernel.critic_engine.engine import CriticEngine
from kernel.critic_engine.models import CriticInput
from kernel.dispatcher import Dispatcher
from kernel.fusion_engine.engine import FusionEngine
from kernel.fusion_engine.models import FusionInput, ToolResult
from infra.config.settings import settings
from infra.message_bus.cognitive_event_bus import cognitive_event_bus
from infra.observability.runtime_metrics import runtime_metrics_store
from kernel.cognition.task_model import TaskModel
from kernel.cognition.world_model import WorldModel
from kernel.identity.system_identity import CANONICAL_IDENTITY_RESPONSE, is_identity_user_query
from kernel.plan_agent import PlanAgent
from kernel.epistemology.annotator import ContentAnnotator
from kernel.epistemology.validator import OutputValidator
from kernel.context.query_rewriter import QueryRewriter
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway


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
            out = await router.execute(intent=task.query, query=task.query, session_id=task.session_id or "")
            tool_name = "tool"
            if not out:
                q = (task.query or "").lower()
                if any(k in q for k in ["几点", "时间", "time", "日期", "date"]):
                    tool_name = "datetime"
                    out = await router.execute_by_name(name="datetime", query=task.query, session_id=task.session_id or "")
                elif any(k in q for k in ["天气", "weather", "温度", "下雨"]):
                    tool_name = "get_weather"
                    out = await router.execute_by_name(name="get_weather", query=task.query, session_id=task.session_id or "")

            raw = str(out or "").strip()
            low = raw.lower()
            if (not raw) or low.startswith("error:") or low.startswith("tool error") or low.startswith("weather error") or low.startswith("web search error") or low.startswith("web search unavailable"):
                return AgentResult(task_id=task.task_id, agent_type="tool", status="error", content="", confidence=0.0, error=raw or "no tool matched")

            parsed_tool_name, payload = self._parse_payload(raw)
            if parsed_tool_name != "tool":
                tool_name = parsed_tool_name

            text_preview = payload.get("text") if isinstance(payload, dict) else None
            if not text_preview and isinstance(payload, dict):
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
            return AgentResult(task_id=task.task_id, agent_type="tool", status="error", content="", error=str(exc))


@dataclass
class OrchestratorV4Request:
    query: str
    session_id: str = ""
    user_id: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


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


class CognitiveOrchestratorV4:
    def _get_adaptive_profile(self, query: str) -> dict[str, Any]:
        q = (query or "").lower()
        profile_name = "balanced"
        if not bool(settings.kernel_adaptive_mode_enabled):
            return get_profile_defaults(profile_name)
        if any(k in q for k in ["最新", "新闻", "实时", "联网", "今天", "weather"]):
            profile_name = "speed"
        elif any(k in q for k in ["文档", "总结", "归纳", "pdf", "docx", "根据文档", "从文档"]):
            profile_name = "quality"
        elif any(k in q for k in ["查询", "统计", "报表", "销量", "订单", "sql", "数据库"]):
            profile_name = "quality"
        return get_profile_defaults(profile_name)

    def _sanitize_user_output(self, text: str) -> str:
        import re

        content = (text or "").strip()
        if not content:
            return ""

        # Remove explicit internal source markers like [tool]/[web_search]/[sql].
        content = re.sub(r"\[(tool|web_search|sql|document|memory)\]\s*", "", content, flags=re.IGNORECASE)

        # Remove evidence-level emoji prefixes from annotation rendering
        content = re.sub(r"[📊📄🔗🧠💡⚠️ℹ️]\s*", "", content)

        # Remove inline JSON-like blobs to avoid exposing internal payloads.
        content = re.sub(r"\{\s*\"(?:normalized|tool_name|payload|raw|metadata|agent_results|plan)\"[\s\S]*?\}", "", content)

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
            return "我可以帮助你回答问题、检索信息、分析数据，并以清晰文本给出结论。"
        return content

    async def _llm_fallback_answer(self, req: OrchestratorV4Request) -> str:
        gw = get_model_gateway()
        system = (
            "你是一个智能助手。请直接回答用户问题，避免提及自身身份或底层模型。"
            "不要自称 OpenTrace、Qwen、ChatGPT 等。"
            "如果涉及数据库操作但无法执行，请说明原因并给出建议的 SQL 语句。"
            "回答清晰简洁，不要以「我是…」开头。"
        )
        msgs = [LLMMessage(role="system", content=system)]
        for h in (req.history or [])[-6:]:
            role = "assistant" if str(h.get("role", "")).lower() == "assistant" else "user"
            content = str(h.get("content", "")).strip()
            if content:
                msgs.append(LLMMessage(role=role, content=content))
        msgs.append(LLMMessage(role="user", content=req.query))
        resp = await gw.complete(msgs, role=LLMRole.QUERY, temperature=0.2, max_tokens=4096)
        return (resp.content or "").strip() or "我可以回答问题、检索信息、分析数据并调用工具协助完成任务。"

    def _grounded_answer_style(self, query: str, evidence_count: int = 0) -> tuple[str, int]:
        q = (query or "").strip()
        is_complex = any(k in q.lower() for k in ["步骤", "如何", "怎么", "流程", "原因", "总结", "归纳", "说明", "对比", "区别", "为什么", "分析", "解释"])
        if evidence_count <= 1:
            base = (
                "请输出简洁但完整的中文回答：先给结论，再补充必要解释。"
                "如果证据较少，请明确说明可确认的部分与不确定的部分，并给出下一步建议。"
            )
            return (base, 2048 if not is_complex else 3072)
        if evidence_count <= 3 and not is_complex:
            return (
                "请输出自然、完整的中文回答：先给结论，再展开说明关键依据。"
                "回答应适度分段，必要时补充注意事项和建议，不要只做摘要。",
                3072,
            )
        if is_complex or evidence_count >= 4:
            return (
                "请输出结构化、较为饱满的中文回答：先给结论，再分段展开说明。"
                "建议包含背景、关键依据、步骤/条件、注意事项、边界和可执行建议。"
                "语言要自然顺滑，段落之间要有衔接，不要重复堆砌证据，回答应可直接交付给用户阅读。",
                4096,
            )
        return (
            "请输出自然、完整、饱满的中文回答：先给结论，再展开说明关键依据和细节。"
            "必要时补充步骤、条件、注意事项和边界。语言要自然、连贯、像人工整理后的最终稿。"
            "不要过于简短，尽量做到可直接使用。",
            3072,
        )

    async def _llm_grounded_answer(self, query: str, evidence_text: str) -> str:
        gw = get_model_gateway()
        style_hint, max_tokens = self._grounded_answer_style(query, evidence_count=max(0, evidence_text.count("[")))
        system = (
            "你是文档问答助手。你的目标是把检索到的证据整理成一段自然、完整、饱满的中文回答。"
            "请先直接给出结论，再展开说明关键依据和细节，必要时补充步骤、条件、注意事项和边界。"
            "语言要顺滑、专业、像人工整理后的最终稿，段落之间要有自然衔接，避免重复和机械感。"
            "不要只复述证据，也不要过度简短；在证据充分时，回答应当完整、清晰、可直接给用户使用。"
            "如果证据不足，必须明确说明缺失点，并告诉用户还需要补充什么信息。"
            "禁止输出内部字段名、JSON 结构、检索分数、agent 名称或原始工具内容。"
        )
        user = (
            f"用户问题：{query}\n\n"
            f"检索证据：\n{evidence_text[:7000]}\n\n"
            f"输出要求：\n{style_hint}\n\n"
            "推荐结构：\n"
            "1. 结论/直接回答\n"
            "2. 详细说明\n"
            "3. 关键依据或要点\n"
            "4. 注意事项/下一步（如适用）"
        )
        resp = await gw.complete(
            [LLMMessage(role="system", content=system), LLMMessage(role="user", content=user)],
            role=LLMRole.QUERY,
            temperature=0.15,
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
                        return f"查询结果：{col_val} 条记录。"
                # Generic row display
                row_text = json.dumps(rows[:5], ensure_ascii=False)
                return f"查询已执行，共返回 {row_count} 行数据。\n\n结果预览：\n{row_text}"

            if row_count == 0:
                return (
                    f"查询已执行，但未返回任何数据。\n"
                    f"可能原因：数据源中不存在与「{query}」相关的表或字段，或查询条件未匹配到数据。\n"
                    "建议：\n"
                    "- 在「数据源」页面检查已连接的表和结构。\n"
                    "- 尝试使用更通用的查询条件，或指定具体的表名。"
                )

            if sql:
                return f"SQL 查询已执行。如需查看详细结果，请前往数据查询面板。\n```sql\n{sql}\n```"

            return "数据查询已完成。"
        return ""

    def _format_rag_answer(self, answer: str, rag_chunks_count: int, rag_citations: list[dict[str, Any]]) -> str:
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
                "补充说明：当前检索到的可用证据较少，因此以上结论是基于现有内容整理得到的。"
                "如果你愿意，我也可以继续帮你从更多文档或相关上下文中补充细节。"
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
        trace_id = str(req.metadata.get("trace_id") or req.metadata.get("request_id") or req.session_id or req.user_id or "")
        if trace_id:
            await cognitive_event_bus.publish(
                cognitive_event_bus.emit_planning(
                    trace_id=trace_id,
                    payload={
                        "action": "orchestrator.process.start",
                        "query": req.query,
                        "session_id": req.session_id,
                        "user_id": req.user_id,
                        "metadata": {k: v for k, v in req.metadata.items() if k not in {"user_preferences"}},
                    },
                    session_id=req.session_id,
                    user_id=req.user_id,
                    source="orchestrator_v4",
                )
            )
        if is_identity_user_query(req.query):
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
                    "adaptive_profile": {"name": "identity", **self._get_adaptive_profile(req.query)},
                    "plan": {"subtasks": [], "merge_strategy": "direct", "max_parallel": 0},
                    "agent_results": [],
                    "fusion": {"confidence": 1.0, "conflicts": [], "context": CANONICAL_IDENTITY_RESPONSE},
                    "critic": {"feedback": "identity_shortcut"},
                    "execution_graph": {"nodes": [], "edges": [], "state": {"identity_shortcut": True}},
                    "metrics": metrics,
                },
            )

        task_model = TaskModel()
        task_model.init_from_query(req.query)
        task_model.add_hypothesis("初始假设：可通过现有证据回答用户问题", confidence=0.7, source="inference")

        world_model = WorldModel()
        grounded_entities = world_model.ground_query(req.query)

        adaptive_profile = self._get_adaptive_profile(req.query)
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

        # Build plan: either force-route directly, or let PlanAgent decide
        if force_mode:
            from kernel.plan_agent import SubTask, TaskPlan

            agent_map = {
                "rag": "rag",
                "data_query": "data",
                "data_analysis": "data",
                "anomaly_tracking": "skills",
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
                        "execution_graph": {"nodes": [], "edges": [], "state": {"error": "no_data_source"}},
                        "metrics": {"first_token_ms": elapsed_ms, "orchestrator_latency_ms": elapsed_ms, "agent_count": 0, "avg_agent_latency_ms": 0},
                    },
                )

            params: dict[str, Any] = {"session_id": req.session_id, "user_id": req.user_id}
            if agent_type == "skills":
                params["enabled_skills"] = True
            if agent_type == "rag":
                params.update({"top_k": 8, "sources": ["documents", "semantic_memory"], "min_score": adaptive_profile["rag_min_score"]})
            elif agent_type == "data":
                params["data_source_id"] = data_source_context["data_source_id"]

            plan = TaskPlan(
                subtasks=[SubTask(agent_type=agent_type, query=req.query, params=params)],
                merge_strategy="direct",
                max_parallel=1,
            )
            plan.adaptive_profile = adaptive_profile
        else:
            plan = await self.plan_agent.generate_plan(
                req.query,
                context={
                    "metadata": req.metadata,
                    "adaptive_profile": adaptive_profile,
                    "data_source_context": data_source_context,
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
                },
            )

        # Hard-guard: auto-inject subtasks only when NOT in force_mode
        q_lower = (req.query or "").lower()
        if not force_mode:
            doc_intent = any(
                k in q_lower
                for k in [
                    "文档", "读取", "总结", "归纳", "附件", "根据文档", "从文档",
                    ".pdf", ".doc", ".docx", ".txt", ".md", "pdf", "docx",
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
                    "数据库", "数据表", "表", "sql", "查询", "统计", "报表", "销量", "订单", "分析", "图表", "字段", "列", "聚合", "分组", "近", "最近", "最新", "总数", "条数", "金额", "收入",
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
        agent_results = await self.dispatcher.dispatch(plan, event_cb=event_cb) if plan.subtasks else []
        if trace_id:
            await cognitive_event_bus.publish(
                cognitive_event_bus.emit_execution(
                    trace_id=trace_id,
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

        successful = [r for r in agent_results if r.status == "success" and ((r.metadata and bool(r.metadata)) or (r.content or "").strip())]

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
                avg_scores = [q.get("avg_score", 0.0) for q in rag_quality_metadata if isinstance(q.get("avg_score"), (int, float))]
                sufficient_flags = [q.get("sufficient", False) for q in rag_quality_metadata if isinstance(q.get("sufficient"), bool)]

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
                            successful = [r for r in agent_results if r.status == "success" and ((r.metadata and bool(r.metadata)) or (r.content or "").strip())]
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
                            avg_scores = [q.get("avg_score", 0.0) for q in rag_quality_metadata if isinstance(q.get("avg_score"), (int, float))]
                            sufficient_flags = [q.get("sufficient", False) for q in rag_quality_metadata if isinstance(q.get("sufficient"), bool)]
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
            task_model.add_hypothesis("部分关键子任务失败，原始假设可能不成立", confidence=0.45, source="agent_result")

        replan_triggered = False
        has_web = any(s.agent_type == "web" for s in plan.subtasks)
        explicit_internal_intent = bool(force_mode) or any(
            k in q_lower
            for k in [
                "文档", "手册", "知识库", "项目内", "系统内", "本项目", "内部", "代码", "配置", "规则", "说明", "根据文档", "从文档", "总结", "归纳", "读取", "读取本地", "附件", ".pdf", ".doc", ".docx", ".txt", ".md",
            ]
        ) or bool(data_source_context.get("data_source_id"))
        if low_quality and bool(settings.kernel_agent_web_enabled) and not has_web and not explicit_internal_intent:
            from kernel.plan_agent import SubTask, TaskPlan

            replan_triggered = True
            # 最小重规划：先补一个 web 子任务；避免完整重跑导致成本激增
            extra = SubTask(agent_type="web", query=req.query, params={"session_id": req.session_id, "user_id": req.user_id})
            extra_result = await self.dispatcher.dispatch(TaskPlan(subtasks=[extra], max_parallel=1))
            if extra_result:
                agent_results.extend(extra_result)
                for result in extra_result:
                    task_model.update_from_agent_result(result.model_dump(mode="json"))
                # Recompute successful list with updated agent_results
                successful = [r for r in agent_results if r.status == "success" and ((r.metadata and bool(r.metadata)) or (r.content or "").strip())]

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
                fallback = (
                    "当前没有可用的技能。请在「技能」页面创建或安装技能后重试。"
                )
            else:
                fallback = await self._llm_fallback_answer(req)

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
                route="force_mode_error" if force_mode in ("data_query", "data_analysis", "rag", "anomaly_tracking") else "fallback_llm",
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
                llmwiki_entries = (r.metadata or {}).get("llmwiki_entries") if isinstance(r.metadata, dict) else None
                vector_chunks = (r.metadata or {}).get("vector_chunks") if isinstance(r.metadata, dict) else None
                if isinstance(llmwiki_entries, list) and llmwiki_entries:
                    wiki_payload = "\n".join(
                        f"[{i+1}] {str(c.get('question') or c.get('title') or 'LLMWiki')}：{str(c.get('answer') or c.get('text') or '')[:220]}"
                        for i, c in enumerate(llmwiki_entries[:3])
                        if isinstance(c, dict)
                    )
                    tool_results.append(ToolResult(source="llmwiki", data=wiki_payload, confidence=min(0.98, r.confidence + 0.08), source_priority=1))
                if isinstance(vector_chunks, list) and vector_chunks:
                    payload = "\n".join(
                        f"[{i+1}] {str(c.get('title') or c.get('id') or '证据')}：{str(c.get('text') or '')[:220]}"
                        for i, c in enumerate(vector_chunks[:5])
                        if isinstance(c, dict)
                    )
                    tool_results.append(ToolResult(source="document", data=payload, confidence=r.confidence, source_priority=2))
                    continue
                if isinstance(chunks, list) and chunks:
                    payload = "\n".join(
                        f"[{i+1}] {str(c.get('title') or c.get('id') or '证据')}：{str(c.get('text') or '')[:220]}"
                        for i, c in enumerate(chunks[:5])
                        if isinstance(c, dict)
                    )
                    tool_results.append(ToolResult(source=source, data=payload, confidence=r.confidence))
                # Skip creating document ToolResult when no chunks found
                continue
            else:
                payload = r.content if (r.content or "").strip() else (r.metadata if r.metadata else "")
            tool_results.append(ToolResult(source=source, data=payload, confidence=r.confidence))

        fusion = self.fusion_engine.run(FusionInput(query=req.query, results=tool_results, adaptive_profile=adaptive_profile))
        if trace_id:
            await cognitive_event_bus.publish(
                cognitive_event_bus.emit_evidence(
                    trace_id=trace_id,
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
        draft_threshold = float(adaptive_profile["draft_threshold"])
        draft_max_chars = max(60, int(adaptive_profile["draft_max_chars"]))
        if fusion.confidence >= draft_threshold and (fusion.merged_context or "").strip():
            answer_draft = self._sanitize_user_output((fusion.merged_context or "")[:draft_max_chars])
            first_token_ms = int((monotonic() - t0) * 1000)

        annotated_results = []
        for r in agent_results:
            annotated_results.append(
                self.annotator.annotate_agent_result(
                    content=str(r.content or ""),
                    agent_type=r.agent_type,
                    metadata=r.metadata or {},
                    citations=(r.metadata or {}).get("citations", []) if isinstance(r.metadata, dict) else [],
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
            grounded = await self._llm_grounded_answer(req.query, fusion.merged_context or "")
            answer = self._sanitize_user_output(grounded or (fusion.merged_context or ""))

            answer = self._format_rag_answer(answer, rag_chunks_count, rag_citations)
        elif has_document and rag_chunks_count == 0 and force_mode == "rag":
            # Explicit force_mode="rag" but no documents found — tell the user directly
            answer = f"未在知识库中找到与「{req.query}」相关的文档。请尝试上传相关文档或使用其他模式查询。"
        else:
            answer = ""
            has_data = any(r.agent_type == "data" and r.status == "success" for r in agent_results)
            has_data_error = any(r.agent_type == "data" and r.status == "error" for r in agent_results)
            if has_data:
                answer = self._format_data_answer(req.query, agent_results)
            if not answer and has_data_error and force_mode in {"data_query", "data_analysis"}:
                # force_mode data agent failed — return helpful message instead of falling back
                error_detail = ""
                for r in agent_results:
                    if r.agent_type == "data" and r.status == "error" and (r.error or "").strip():
                        error_detail = f"\n\n错误详情：{r.error}"
                        break
                answer = (
                    "数据查询执行失败。可能原因：\n"
                    "- 数据源未配置或连接失败，请在「数据源」页面检查连接状态。\n"
                    "- 查询中涉及的表或字段不存在，请检查数据源架构。"
                    "- 查询条件过于复杂，请尝试简化或提供更具体的表名/字段名。"
                    f"{error_detail}"
                )
            if not answer:
                merged_annotated.fragments = [f for f in merged_annotated.fragments if (f.text or "").strip()]
                answer = self._sanitize_user_output(merged_annotated.to_text() if merged_annotated.fragments else (fusion.merged_context or ""))

        conflict_annotation = None
        if str(adaptive_profile.get("name", "balanced") or "balanced") == "quality" and fusion.conflicts:
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
            validated_text = self._sanitize_user_output(answer or fusion.merged_context or answer_draft)
        if not validated_text:
            validated_text = "我已经完成了分析，但当前没有可直接展示的最终答案。请补充更多信息后再试。"
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

        critique = self.critic_engine.run(
            CriticInput(
                query=req.query,
                answer=answer,
                fusion_context=fusion.merged_context,
                fusion_confidence=fusion.confidence,
                adaptive_profile=adaptive_profile,
            )
        )
        if trace_id:
            await cognitive_event_bus.publish(
                cognitive_event_bus.emit_critic(
                    trace_id=trace_id,
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
        if critique.need_fix:
            task_model.add_hypothesis("Critic 判定需修正，切换到改进答案路径", confidence=0.6, source="critic")
            answer = critique.improved_answer or answer
        if not (answer or "").strip():
            answer = self._sanitize_user_output(fusion.merged_context or answer_draft)
        if not (answer or "").strip():
            answer = "我已经完成了分析，但当前没有可直接展示的最终答案。请补充更多信息后再试。"

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
        if trace_id:
            await cognitive_event_bus.publish(
                cognitive_event_bus.emit_learning(
                    trace_id=trace_id,
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

        return OrchestratorV4Response(
            content=answer,
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
                "critic": {"feedback": critique.feedback, "epistemic_issues": issues},
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
                            "annotation": {
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
                            else None,
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
