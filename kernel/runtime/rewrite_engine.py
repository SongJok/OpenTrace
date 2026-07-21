"""
RewriteEngine — Context-aware query canonicalization.

Fuses multi-turn conversation history, user profile, workspace state,
historical artifacts, memory context, and organizational policy into a
single RuntimeCanonicalQuery.

This is the Runtime Grounding Layer — every query passes through here
before any other cognitive processing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kernel.runtime.context import RuntimeContext
    from kernel.runtime.objects import RuntimeCanonicalQuery

from infra.observability.logger import get_logger

logger = get_logger(__name__)

# Max chars of conversation history to feed into the rewriter
_MAX_HISTORY_CHARS = 2000
# Max chars of memory context
_MAX_MEMORY_CHARS = 1200
# Min query length to skip LLM rewrite (single-turn, no context + short = fast path)
_FAST_PATH_MAX_QUERY_LEN = 80


class RewriteEngine:
    """Context-aware query rewriting — the Runtime Grounding Layer.

    Fuses all available context into a fully-resolved canonical query
    that captures what the user *actually* wants.
    """

    def __init__(self) -> None:
        pass

    async def rewrite(self, query: str, ctx: RuntimeContext) -> RuntimeCanonicalQuery:
        """Rewrite the raw user query into a canonical form.

        Fast path: single-turn, short & self-contained → return directly.
        LLM path: multi-turn, ambiguous, or rich context → one LLM call.
        """
        from kernel.runtime.objects import RuntimeCanonicalQuery

        protected_intent = getattr(ctx, "protected_intent", "") or query.strip()
        task_type = getattr(ctx, "task_type", "")
        budget = getattr(ctx, "cognitive_budget", {}) or {}
        if task_type in {"greeting", "identity", "capability_help", "usage_help"}:
            return RuntimeCanonicalQuery(
                raw_query=query,
                normalized_query=query.strip(),
                protected_intent=protected_intent,
                canonical_query=query.strip(),
                original_query=query,
                rewrite_trace="intent_lock:protected_simple",
            )

        # ── Fast path: no conversation history, no memory, short query ──
        has_history = bool(ctx.conversation_history)
        has_memory = bool(ctx.memory_context) and bool(budget.get("memory_injection", True))
        has_workspace = bool(ctx.workspace_state) and bool(budget.get("workspace_context", True))
        is_short = len(query) <= _FAST_PATH_MAX_QUERY_LEN

        if not has_history and not has_memory and not has_workspace and is_short:
            logger.debug("RewriteEngine fast path — single-turn short query")
            return RuntimeCanonicalQuery(
                raw_query=query,
                normalized_query=query.strip(),
                protected_intent=protected_intent,
                canonical_query=query.strip(),
                original_query=query,
                rewrite_trace="fast_path:no_context",
            )

        # ── LLM path: full context fusion ──
        try:
            return await self._rewrite_via_llm(query, ctx)
        except Exception as exc:
            logger.error("RewriteEngine LLM call failed, returning original query", error=str(exc))
            return RuntimeCanonicalQuery(
                raw_query=query,
                normalized_query=query.strip(),
                protected_intent=protected_intent,
                canonical_query=query.strip(),
                original_query=query,
                rewrite_trace=f"error_fallback:{str(exc)[:100]}",
            )

    # ── LLM-based rewrite ──────────────────────────────────────────────────

    async def _rewrite_via_llm(self, query: str, ctx: RuntimeContext) -> RuntimeCanonicalQuery:
        from kernel.runtime.objects import RuntimeCanonicalQuery

        from model.model_gateway.gateway import LLMMessage, LLMRole, get_model_gateway

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(query, ctx)

        gw = get_model_gateway()
        resp = await gw.complete(
            [
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_prompt),
            ],
            role=LLMRole.QUERY,
            temperature=0.0,
            max_tokens=600,
        )
        text = (resp.content or "").strip()

        return self._parse_rewrite_result(text, query)

    def _build_system_prompt(self) -> str:
        return """你是 Runtime Query Rewriter。你的任务是将用户的简短追问扩展为完整、规范的查询。

## 你需要融合以下上下文
1. 多轮对话历史 — 将"继续"、"刚才那个"等指代消解为具体内容
2. 用户偏好 — 调整查询的表达方式和详细程度
3. 工作空间状态 — 当前 session 已有的 artifact 和数据
4. 组织策略 — 遵守权限和合规约束

## 输出格式（纯 JSON，无 markdown 包裹）
{
  "canonical_query": "完整规范化的查询",
  "entity_resolutions": {"指代词": "消解后的实体"},
  "workspace_references": ["引用的 artifact 名称"],
  "policy_constraints": ["需要遵守的约束"],
  "rewrite_trace": "简短的重写说明"
}

## 规则
1. 如果原文已经完整清晰，canonical_query 就是原文（修剪空白后）
2. 指代消解必须基于对话历史中的实际内容，不要猜测
3. entity_resolutions 只放实际消解了的指代
4. 不要添加用户没有问的内容
5. 保持用户的语言风格（简短/详细）"""

    def _build_user_prompt(self, query: str, ctx: RuntimeContext) -> str:
        parts: list[str] = [f"## 用户原始提问\n{query}"]

        if ctx.conversation_history:
            recent = ctx.conversation_history[-6:]
            lines = []
            for h in recent:
                role = h.get("role", "?")
                content = str(h.get("content", ""))[:_MAX_HISTORY_CHARS // 6]
                lines.append(f"[{role}]: {content}")
            parts.append(f"## 对话历史\n" + "\n".join(lines))

        if ctx.memory_context:
            parts.append(f"## 相关记忆\n{ctx.memory_context[:_MAX_MEMORY_CHARS]}")

        if ctx.preference_context_block:
            parts.append(f"## 用户偏好\n{ctx.preference_context_block[:800]}")

        if ctx.workspace_state:
            ws = ctx.workspace_state
            if isinstance(ws, dict):
                artifact_names = []
                for wname, wdata in ws.items():
                    if isinstance(wdata, dict):
                        for a in wdata.get("_artifacts", []):
                            if isinstance(a, dict):
                                artifact_names.append(a.get("name", ""))
                if artifact_names:
                    parts.append(f"## 工作空间已有 Artifact\n{', '.join(artifact_names)}")

        return "\n\n".join(parts)

    def _parse_rewrite_result(self, text: str, original_query: str) -> RuntimeCanonicalQuery:
        import json
        import re

        from kernel.runtime.objects import RuntimeCanonicalQuery

        text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        text = re.sub(r"\n?\s*```\s*$", "", text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("RewriteEngine JSON parse failed", raw=text[:200])
            return RuntimeCanonicalQuery(
                raw_query=original_query,
                normalized_query=original_query.strip(),
                protected_intent=original_query.strip(),
                canonical_query=original_query.strip(),
                original_query=original_query,
                rewrite_trace="parse_fallback",
            )

        return RuntimeCanonicalQuery(
            raw_query=original_query,
            normalized_query=str(data.get("canonical_query", original_query)).strip(),
            protected_intent=original_query.strip(),
            canonical_query=str(data.get("canonical_query", original_query)).strip(),
            original_query=original_query,
            entity_resolutions=data.get("entity_resolutions", {}) or {},
            workspace_references=data.get("workspace_references", []) or [],
            policy_constraints=data.get("policy_constraints", []) or [],
            rewrite_trace=str(data.get("rewrite_trace", "")),
        )
