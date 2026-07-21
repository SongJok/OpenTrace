"""指代解析 — 纠正检测、索引/类型引用与多轮 query 展开（确定性规则，无 LLM 硬依赖）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_CORRECTION_RE = re.compile(
    r"(不对|错了|不是|应该是|其实是|改一下|换成|按.*算|重新|更正)",
    re.IGNORECASE,
)
_INDEX_REF_RE = re.compile(
    r"(第一个|第二个|第三个|上面|上一个|那条|那个|这份|这张表|刚才)",
)
_TYPE_REF_RE = re.compile(
    r"(表结构|字段|列|sql|查询结果|图表|文档|来源)",
    re.IGNORECASE,
)
# Must match explicit continuation — do not treat every short utterance as follow-up.
_EXPLICIT_FOLLOW_UP_RE = re.compile(
    r"^(那|那么|还有|另外|具体|详细|按|根据|再|继续|刚才|上面|上一个)",
)


@dataclass
class ReferenceResult:
    is_correction: bool = False
    corrected_query: str = ""
    references: list[dict] = field(default_factory=list)
    # V4 / legacy orchestrator contract fields
    confidence: float = 0.0
    turn_type: str = "neutral"
    resolved_query: str = ""
    corrected_constraints: dict[str, Any] = field(default_factory=dict)
    suggested_domain: str = ""
    suggested_agent: str = ""


class ReferenceResolver:

    def _refs_from_state(self, conversation_state: Any, result_refs: Any) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        if result_refs:
            if isinstance(result_refs, list):
                refs.extend([r for r in result_refs if isinstance(r, dict)])
        if conversation_state is not None:
            last_refs = getattr(conversation_state, "last_result_refs", None) or []
            if isinstance(last_refs, list):
                for r in last_refs:
                    if isinstance(r, dict) and r not in refs:
                        refs.append(r)
            last_results = getattr(conversation_state, "last_results", None) or []
            if isinstance(last_results, list):
                for r in last_results:
                    if isinstance(r, dict):
                        refs.append(r)
        return refs

    def _expand_index_reference(self, query: str, refs: list[dict[str, Any]]) -> str:
        if not refs:
            return query
        q = (query or "").strip()
        idx = 0
        if "第二个" in q or "第二条" in q:
            idx = 1
        elif "第三个" in q or "第三条" in q:
            idx = 2
        if idx >= len(refs):
            idx = 0
        ref = refs[idx] if refs else {}
        title = str(ref.get("title") or ref.get("summary") or "").strip()
        ref_type = str(ref.get("type") or ref.get("ref_type") or "").strip()
        payload = ref.get("payload") if isinstance(ref.get("payload"), dict) else {}
        snippet = str(payload.get("text") or payload.get("chunk") or ref.get("summary") or "")[:120]
        if title and snippet:
            return f"{q}（引用：{title} — {snippet}）"
        if title:
            return f"{q}（引用：{title}）"
        if ref_type:
            return f"{q}（引用类型：{ref_type}）"
        return q

    def _detect_correction(self, query: str, conversation_state: Any) -> ReferenceResult:
        q = (query or "").strip()
        if not _CORRECTION_RE.search(q):
            return ReferenceResult()
        last_goal = ""
        if conversation_state is not None:
            last_goal = str(getattr(conversation_state, "last_user_goal", "") or "").strip()
        corrected = q
        if last_goal and last_goal not in q:
            corrected = f"{last_goal}；用户纠正：{q}"
        constraints: dict[str, Any] = {}
        if conversation_state is not None:
            ac = getattr(conversation_state, "active_constraints", None)
            if isinstance(ac, dict):
                constraints = dict(ac)
            constraints["user_correction"] = q
        domain = str(getattr(conversation_state, "active_domain", "") or "") if conversation_state else ""
        return ReferenceResult(
            is_correction=True,
            corrected_query=corrected,
            references=[],
            confidence=0.72,
            turn_type="correction",
            resolved_query=corrected,
            corrected_constraints=constraints,
            suggested_domain=domain,
            suggested_agent="",
        )

    def _detect_follow_up_reference(self, query: str, refs: list[dict[str, Any]]) -> ReferenceResult:
        q = (query or "").strip()
        if not q or not refs:
            return ReferenceResult()
        if not (_INDEX_REF_RE.search(q) or _TYPE_REF_RE.search(q)):
            return ReferenceResult()
        resolved = self._expand_index_reference(q, refs)
        if resolved == q:
            return ReferenceResult()
        ref_types = {str(r.get("type", "")) for r in refs if isinstance(r, dict)}
        suggested_agent = ""
        if "doc_chunk" in ref_types or "citation" in ref_types:
            suggested_agent = "rag"
        elif "data_table" in ref_types or "sql" in ref_types:
            suggested_agent = "data"
        return ReferenceResult(
            is_correction=False,
            corrected_query=resolved,
            references=refs[:3],
            confidence=0.58,
            turn_type="reference",
            resolved_query=resolved,
            suggested_domain="",
            suggested_agent=suggested_agent,
        )

    async def resolve_with_llm(
        self,
        query: str,
        conversation_state: Any = None,
        result_refs: Any = None,
    ) -> ReferenceResult:
        """规则优先的指代解析；保留 async 签名供 orchestrator 与 kernel 统一调用。"""
        q = (query or "").strip()
        if not q:
            return ReferenceResult()

        correction = self._detect_correction(q, conversation_state)
        if correction.confidence >= 0.5:
            return correction

        refs = self._refs_from_state(conversation_state, result_refs)
        follow = self._detect_follow_up_reference(q, refs)
        if follow.confidence >= 0.5:
            return follow

        # 短追问：仅在有明确续问标记时拼接上一轮目标（避免新话题短句被当成第一轮）
        if (
            conversation_state is not None
            and len(q) <= 18
            and _EXPLICIT_FOLLOW_UP_RE.search(q)
        ):
            last_goal = str(getattr(conversation_state, "last_user_goal", "") or "").strip()
            if last_goal and last_goal not in q:
                resolved = f"{last_goal}；追问：{q}"
                return ReferenceResult(
                    confidence=0.52,
                    turn_type="follow_up",
                    resolved_query=resolved,
                    corrected_query=resolved,
                    references=refs[:2],
                    suggested_domain=str(getattr(conversation_state, "active_domain", "") or ""),
                )

        return ReferenceResult(resolved_query=q, confidence=0.0, turn_type="neutral")