"""Web Intelligence Agent V3 — search → rank → trust → evidence graph."""

from __future__ import annotations

import json
import re

from agents.base import AgentResult, TaskMessage
from agents.cognitive_agent import CognitiveAgent
from execution.tool_router.router import ToolRouter
from services.evidence_graph.engine import rank_evidence
from services.rag_evidence_intelligence import enrich_evidence_intelligence


class WebIntelligenceAgent(CognitiveAgent):
    def __init__(self) -> None:
        super().__init__("web_intelligence")

    @staticmethod
    def _upstream_error(raw: str) -> str | None:
        normalized = (raw or "").strip()
        lowered = normalized.lower()
        error_prefixes = (
            "error:",
            "tool error (",
            "web fetch error:",
            "web fetch unavailable:",
            "web search error:",
            "web search unavailable:",
        )
        if any(lowered.startswith(prefix) for prefix in error_prefixes):
            return normalized
        try:
            payload = json.loads(normalized)
        except (TypeError, ValueError):
            return None
        if isinstance(payload, dict) and str(payload.get("status") or "").lower() in {
            "error",
            "failed",
            "timeout",
        }:
            return str(payload.get("error") or payload.get("message") or "web search failed")
        return None

    def _items_from_raw(self, raw: str) -> list[dict]:
        s = (raw or "").strip()
        if not s or self._upstream_error(s):
            return []
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                items = obj.get("items") or obj.get("results") or []
            elif isinstance(obj, list):
                items = obj
            else:
                items = []
        except Exception:
            return [{"content": s[:800], "source": "web_search", "source_type": "web"}]
        out: list[dict] = []
        for i, it in enumerate(items[:12]):
            if isinstance(it, dict):
                out.append(
                    {
                        "id": f"w{i}",
                        "content": str(
                            it.get("snippet") or it.get("summary") or it.get("title") or ""
                        ),
                        "snippet": str(it.get("snippet") or ""),
                        "title": str(it.get("title") or ""),
                        "url": str(it.get("url") or ""),
                        "source": str(it.get("url") or "web"),
                        "source_type": "web",
                        "credibility_score": 0.55,
                        "relevance_score": 0.6,
                    }
                )
        return out

    @staticmethod
    def _search_query_from_task(task: TaskMessage) -> str:
        params = task.params or {}
        miq = str(params.get("memory_injection_query", "") or "").strip()
        if miq:
            return miq
        mtr = params.get("multi_turn_resolution")
        if isinstance(mtr, dict):
            rq = str(mtr.get("resolved_query", "") or "").strip()
            if rq:
                return rq
        return (task.query or "").strip()

    async def execute_core(self, task: TaskMessage, plan: dict) -> AgentResult:
        search_q = self._search_query_from_task(task)
        router = ToolRouter()
        url_match = re.search(r"https?://[^\s<>'\"]+", search_q, re.IGNORECASE)
        if url_match:
            out = await router.execute_by_name(
                name="web_fetch",
                url=url_match.group(0).rstrip(".,，。!?！？"),
                session_id=task.session_id or "",
            )
        else:
            out = await router.execute_by_name(
                name="web_search", query=search_q, session_id=task.session_id or ""
            )
        raw = str(out or "").strip()
        upstream_error = self._upstream_error(raw)
        items = self._items_from_raw(raw)
        if not items:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="error",
                content="",
                confidence=0.0,
                error=upstream_error or raw or "empty web results",
            )
        coverage_meta: dict = {}
        ranked = rank_evidence(items)
        intel = enrich_evidence_intelligence(items, query=search_q, source_kind="web")
        ranked = intel.get("ranked_chunks") or ranked
        try:
            from infra.config.settings import settings

            if bool(getattr(settings, "kernel_web_coverage_evaluator_enabled", True)):
                from agents.web_intelligence.coverage_evaluator import evaluate_coverage

                max_rounds = int(getattr(settings, "kernel_web_coverage_max_rounds", 2) or 2)
                round_idx = 0
                report = evaluate_coverage(search_q, ranked, round_index=round_idx)
                while not url_match and report.should_supplement and round_idx + 1 < max_rounds:
                    sup_q = (report.supplement_queries or [search_q])[0]
                    extra_raw = await router.execute_by_name(
                        name="web_search", query=sup_q, session_id=task.session_id or ""
                    )
                    extra_items = self._items_from_raw(str(extra_raw or ""))
                    if extra_items:
                        items.extend(extra_items)
                        ranked = rank_evidence(items)
                        intel = enrich_evidence_intelligence(
                            items, query=search_q, source_kind="web"
                        )
                        ranked = intel.get("ranked_chunks") or ranked
                    round_idx += 1
                    report = evaluate_coverage(search_q, ranked, round_index=round_idx)
                coverage_meta = report.to_metadata()
        except Exception:
            pass
        synthesis = str(intel.get("synthesis_preview") or "")
        lines = []
        for i, it in enumerate(ranked[:5], 1):
            lines.append(f"{i}. {it.get('title') or it.get('content', '')[:120]}")
        content = "\n".join(lines) if lines else synthesis[:1200]
        conf = float(plan.get("reasoning_confidence", 0.65))
        ev_objs = []
        for it in ranked[:8]:
            snippet = str(it.get("content") or it.get("snippet") or it.get("title") or "")[:4000]
            if snippet:
                ev_objs.append(
                    self._make_evidence_object(
                        content=snippet,
                        source_type="web",
                        credibility=float(it.get("credibility_score", 0.55)),
                        relevance=float(it.get("relevance_score", 0.6)),
                        url=str(it.get("url") or ""),
                    )
                )
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=content,
            confidence=conf,
            metadata={
                "evidence_graph": intel.get("evidence_graph") or {},
                "rag_evidence_intelligence": intel,
                "web_coverage": coverage_meta,
                "web_intelligence": True,
                "synthesis_preview": synthesis[:500],
                "chunk_graph": intel.get("chunk_graph"),
                "fact_verification": intel.get("fact_verification"),
            },
            evidence_objects=ev_objs,
        )
