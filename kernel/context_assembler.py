"""
上下文组装器 — V5 路由层的结构化上下文组装。

V5 架构链路：
  Legacy cognitive context adapter; canonical chat uses kernel.agent_loop.context.

将对话历史、记忆、附件与 conversation_state 组织为块；超 token 预算时标记待压缩
（委托 ContextComposer 或编排器压缩器）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_MAX_HISTORY_TOKENS = 4096
_DEFAULT_MAX_ATTACHMENT_TOKENS = 2048
_DEFAULT_MAX_MEMORY_TOKENS = 1024
_EST_CHARS_PER_TOKEN = 4


@dataclass
class StructuredSummary:
    sections: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        return "\n".join(self.sections)


@dataclass
class AssembledContext:
    structured_summary: StructuredSummary = field(default_factory=StructuredSummary)
    compressed: bool = False
    total_tokens: int = 0
    recent_turns: list[dict[str, str]] = field(default_factory=list)
    memory_injection_query: str = ""
    summary_block: str = ""
    memory_block: str = ""
    attachment_block: str = ""
    state_block: str = ""


class ContextAssembler:
    """从对话状态组装结构化上下文块。

    不调用 LLM — 纯组装和 token 预算管理。
    需要压缩时，由编排器的上下文组合器处理。
    """

    def __init__(
        self,
        max_history_tokens: int | None = None,
        max_attachment_tokens: int | None = None,
        max_memory_tokens: int | None = None,
    ) -> None:
        self._max_history = max_history_tokens or int(
            getattr(settings, "context_max_history_tokens", _DEFAULT_MAX_HISTORY_TOKENS)
        )
        self._max_attachment = max_attachment_tokens or int(
            getattr(settings, "context_max_attachment_tokens", _DEFAULT_MAX_ATTACHMENT_TOKENS)
        )
        self._max_memory = max_memory_tokens or int(
            getattr(settings, "context_max_memory_tokens", _DEFAULT_MAX_MEMORY_TOKENS)
        )

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        try:
            from kernel.token_counter import count_tokens
            return count_tokens(text)
        except Exception:
            cjk = sum(1 for c in text if "一" <= c <= "鿿" or "㐀" <= c <= "䶿")
            other = len(text) - cjk
            return max(1, int(cjk / 2 + other / 4))

    def _format_history_turns(
        self, history: list | None
    ) -> tuple[list[dict[str, str]], int]:
        if not history:
            return [], 0

        turns: list[dict[str, str]] = []
        total_tokens = 0
        for entry in history:
            if isinstance(entry, dict):
                role = entry.get("role", "user")
                content = str(entry.get("content", ""))
                tokens = self._estimate_tokens(content)
                if total_tokens + tokens > self._max_history and turns:
                    break
                turns.append({"role": role, "content": content})
                total_tokens += tokens
            elif isinstance(entry, str):
                tokens = self._estimate_tokens(entry)
                if total_tokens + tokens > self._max_history and turns:
                    break
                turns.append({"role": "user", "content": entry})
                total_tokens += tokens

        return turns, total_tokens

    def _build_memory_block(self, memory_context: list | None) -> tuple[str, int]:
        if not memory_context:
            return "", 0

        chunks: list[str] = []
        total_tokens = 0
        for mc in memory_context:
            if isinstance(mc, dict):
                content = str(mc.get("content", ""))
                score = mc.get("score", 0)
                source = mc.get("source", "")
                line = f"[{source}] {content}" if source else content
            else:
                line = str(mc)
                score = 0

            tokens = self._estimate_tokens(line)
            if total_tokens + tokens > self._max_memory:
                break
            chunks.append(line)
            total_tokens += tokens

        return "\n".join(chunks), total_tokens

    def _build_attachment_block(self, attachment_contexts: list | None) -> tuple[str, int]:
        if not attachment_contexts:
            return "", 0

        chunks: list[str] = []
        total_tokens = 0
        for att in attachment_contexts:
            if isinstance(att, dict):
                name = att.get("name", att.get("filename", ""))
                snippet = str(att.get("content", att.get("snippet", "")))
                line = f"[Attachment: {name}]\n{snippet}"
            else:
                line = str(att)
            tokens = self._estimate_tokens(line)
            if total_tokens + tokens > self._max_attachment:
                chunks.append(f"[{len(attachment_contexts) - len(chunks)} more attachments omitted]")
                total_tokens += 100
                break
            chunks.append(line)
            total_tokens += tokens

        return "\n\n".join(chunks), total_tokens

    def _build_state_block(self, conversation_state) -> str:
        if conversation_state is None:
            return ""

        if hasattr(conversation_state, "to_db_dict"):
            cs_dict = conversation_state.to_db_dict()
        elif isinstance(conversation_state, dict):
            cs_dict = conversation_state
        else:
            return ""

        parts: list[str] = []
        topic = cs_dict.get("active_topic", "")
        if topic:
            parts.append(f"当前话题: {topic}")

        intent = cs_dict.get("active_intent", "")
        if intent:
            parts.append(f"预期意图: {intent}")

        phase = cs_dict.get("conversation_phase", "")
        if phase:
            parts.append(f"对话阶段: {phase}")

        last_goal = cs_dict.get("last_user_goal", "")
        if last_goal:
            parts.append(f"上一轮目标: {last_goal[:200]}")

        domain = cs_dict.get("active_domain", "") or cs_dict.get("active_intent", "")
        if domain:
            parts.append(f"活跃领域: {domain}")

        constraints = cs_dict.get("active_constraints", {})
        if isinstance(constraints, dict) and constraints:
            corr = constraints.get("user_correction")
            if corr:
                parts.append(f"用户纠正: {str(corr)[:160]}")
            other = {k: v for k, v in constraints.items() if k != "user_correction" and v}
            if other:
                parts.append(f"活跃约束: {other}")

        last_turn = cs_dict.get("last_turn_type", "")
        if last_turn:
            parts.append(f"上一轮类型: {last_turn}")

        last_results = cs_dict.get("last_results", [])
        if last_results:
            parts.append(self._summarize_last_results(last_results))

        summary = cs_dict.get("conversation_summary", "")
        if summary:
            parts.append(f"对话摘要: {summary}")
        entities = cs_dict.get("active_entities", [])
        if entities:
            parts.append(f"活跃实体: {', '.join(str(e) for e in entities)}")

        ext = cs_dict.get("state_extension") or {}
        if isinstance(ext, dict):
            prefs = ext.get("learned_preferences", {})
            if prefs:
                parts.append(f"用户偏好: {prefs}")

        return "\n".join(parts)

    @staticmethod
    def _summarize_last_results(results: list) -> str:
        """从上一轮结果中提取列名、数据源等关键信息。"""
        try:
            columns: set[str] = set()
            sources: set[str] = set()
            for r in results:
                if isinstance(r, dict):
                    if "columns" in r:
                        cols = r["columns"]
                        if isinstance(cols, list):
                            for c in cols:
                                if isinstance(c, str):
                                    columns.add(c)
                    if "source" in r:
                        sources.add(str(r["source"]))
                    if "data_source" in r:
                        sources.add(str(r["data_source"]))
            parts: list[str] = []
            if columns:
                parts.append(f"上一轮结果列: {', '.join(sorted(columns)[:15])}")
            if sources:
                parts.append(f"上一轮数据源: {', '.join(sorted(sources)[:5])}")
            return "\n".join(parts) if parts else ""
        except Exception:
            return ""

    async def assemble(self, tctx) -> AssembledContext:
        if tctx is None:
            return AssembledContext()

        sections: list[str] = []
        total_tokens = 0
        compressed = False

        # ── 1. 历史对话轮次 ────────────────────────────────────────────
        recent_turns, history_tokens = self._format_history_turns(tctx.recent_history)
        total_tokens += history_tokens
        if recent_turns:
            history_lines = [f"{t['role']}: {t['content'][:200]}" for t in recent_turns[-6:]]
            sections.append("## 最近对话\n" + "\n".join(history_lines))

        if history_tokens > self._max_history:
            compressed = True

        # ── 2. 记忆上下文块 ─────────────────────────────────────
        memory_block, memory_tokens = self._build_memory_block(tctx.memory_context)
        if memory_block:
            total_tokens += memory_tokens
            sections.append("## 记忆上下文\n" + memory_block)

        # ── 3. 附件块 ─────────────────────────────────────────
        attachment_contexts = getattr(tctx, "attachment_contexts", None) or []
        attachment_block, attachment_tokens = self._build_attachment_block(attachment_contexts)
        if attachment_block:
            total_tokens += attachment_tokens
            sections.append("## 附件内容\n" + attachment_block)

        # ── 4. 对话状态块 ─────────────────────────────────────────
        conv_state = getattr(tctx, "conversation_state", None)
        state_block = self._build_state_block(conv_state)
        if state_block:
            total_tokens += self._estimate_tokens(state_block)
            sections.append("## 对话状态\n" + state_block)

        # ── 5. 记忆注入查询 ───────────────────────────────────
        # 必须使用当前轮 query；勿用 history 中「最后一条 user」（多为上一轮，会导致 RAG/记忆检索串轮）
        query = (getattr(tctx, "query", "") or "").strip()
        md = getattr(tctx, "metadata", None) or {}
        if isinstance(md, dict):
            raw = str(md.get("raw_user_query") or "").strip()
            if raw:
                query = raw

        return AssembledContext(
            structured_summary=StructuredSummary(sections=sections),
            compressed=compressed,
            total_tokens=total_tokens,
            recent_turns=recent_turns,
            memory_injection_query=query,
            summary_block=StructuredSummary(sections=sections).to_text(),
            memory_block=memory_block,
            attachment_block=attachment_block,
            state_block=state_block,
        )


_assembler: ContextAssembler | None = None


def get_context_assembler() -> ContextAssembler:
    global _assembler
    if _assembler is None:
        _assembler = ContextAssembler()
    return _assembler
