from __future__ import annotations

import re
from typing import Any

from infra.config.settings import settings
from model.model_gateway.gateway import LLMRole, get_model_gateway


class QueryRewriter:
    """Query rewrite for recall robustness and quality improvement."""

    async def rewrite(
        self,
        query: str,
        history: list[dict[str, str]] | None = None,
        conversation_state: Any = None,
    ) -> str:
        q = (query or "").strip()
        if not q:
            return q
        # Clean whitespace and noise prefixes
        q = " ".join(q.split())
        for prefix in ["请你", "麻烦", "帮我"]:
            if q.startswith(prefix):
                q = q[len(prefix) :].strip()

        # Resolve deictic references using conversation context
        if history and _has_deictic(q):
            q = _resolve_deictic(q, history, conversation_state)

        return q

    async def rewrite_with_rag_context(
        self,
        original_query: str,
        rag_chunks: list[dict[str, Any]],
        max_terms: int = 10,
    ) -> str:
        """
        Improve search query using original query and low-quality RAG chunks.
        Strategy:
        1. Extract key terms from original query
        2. Extract salient terms from top chunks (even if low score)
        3. Combine terms, removing duplicates
        4. Optionally use LLM for query refinement if enabled and time permits
        """
        if not rag_chunks:
            return original_query

        # Extract terms from original query
        orig_terms = self._extract_terms(original_query)

        # Extract terms from top chunks (limit to 3 chunks to avoid noise)
        chunk_terms = []
        for chunk in rag_chunks[:3]:
            text = chunk.get("text", "")[:500]  # limit length
            title = chunk.get("title", "")
            combined = f"{title} {text}"
            chunk_terms.extend(self._extract_terms(combined))

        # Combine and deduplicate terms
        all_terms = list(dict.fromkeys(orig_terms + chunk_terms))

        # Limit total terms
        if len(all_terms) > max_terms:
            # Prioritize original query terms, then chunk terms
            orig_set = set(orig_terms)
            chunk_only = [t for t in all_terms if t not in orig_set]
            all_terms = orig_terms + chunk_only[: max_terms - len(orig_terms)]

        # Build improved query
        improved = " ".join(all_terms)

        # If LLM query refinement is enabled and we have enough context
        if getattr(settings, "enable_llm_query_refinement", False) and rag_chunks:
            try:
                improved = await self._llm_refine_query(original_query, rag_chunks[:2], improved)
            except Exception:
                # Fall back to term-based improvement
                pass

        return improved.strip() or original_query

    def _extract_terms(self, text: str) -> list[str]:
        """Extract meaningful terms from text (Chinese words and alphanumeric)."""
        if not text:
            return []
        # Chinese characters (2+ consecutive) and alphanumeric words
        terms = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{2,}", text.lower())
        # Remove very short terms (single chars may be noise)
        return [t for t in terms if len(t) >= 2]

    async def _llm_refine_query(
        self,
        original_query: str,
        rag_chunks: list[dict[str, Any]],
        term_based_query: str,
    ) -> str:
        """Use LLM to refine search query based on original query and RAG context."""
        # Prepare context from chunks
        context_parts = []
        for i, chunk in enumerate(rag_chunks[:2], 1):
            text = chunk.get("text", "")[:300]
            score = chunk.get("score", 0.0)
            context_parts.append(f"[Chunk {i}, score={score:.2f}]: {text}")

        context_str = "\n".join(context_parts)

        prompt = f"""Original user query: "{original_query}"

We retrieved these document chunks (with low relevance scores):
{context_str}

Current term-based improved query: "{term_based_query}"

Please generate a better search query that will help find more relevant information.
The improved query should:
1. Focus on the core intent of the original query
2. Include missing key concepts from the retrieved chunks
3. Be concise (under 20 words)
4. Use natural language appropriate for document search

Improved query:"""

        from model.model_gateway.gateway import LLMMessage

        messages = [
            LLMMessage(role="system", content="You are a search query optimization assistant."),
            LLMMessage(role="user", content=prompt),
        ]

        gateway = get_model_gateway()
        response = await gateway.complete(messages, role=LLMRole.QUERY)
        refined = response.content.strip().strip('"').strip()

        # Fallback if LLM returns empty or nonsense
        if not refined or len(refined) < 3:
            return term_based_query

        return refined


# ── Deictic resolution helpers ─────────────────────────────────────────────

_DEICTIC_PATTERNS = [
    (r"(它|它们|他|她|其)", "that entity"),
    (r"(这个|那个|这些|那些)", "that one"),
    (r"前(一[个次]|[面面]的|文)?[提说到]", "previous mention"),
    (r"(刚[才刚]的|上一次|上[一-]?[个次])", "previous turn"),
    (r"第[一二三四五六七八九十\d]+[个条]", "numbered reference"),
]


def _has_deictic(query: str) -> bool:
    for pattern, _ in _DEICTIC_PATTERNS:
        if __import__("re").search(pattern, query):
            return True
    return False


def _resolve_deictic(
    query: str,
    history: list[dict[str, str]],
    conversation_state: Any = None,
) -> str:
    """Inject context from recent conversation to resolve pronoun references."""
    # Extract entities from recent assistant responses
    recent_entities: list[str] = []
    for msg in reversed(history[-6:]):
        if msg.get("role") == "assistant":
            content = str(msg.get("content", ""))
            # Extract entities: quoted strings, proper nouns, data terms
            entities = __import__("re").findall(
                r'(?:["“]([^"”]+)["”]|([一-鿿]{2,6}(?:销量|订单|利润|数据|指标|报表|查询|增长|下降)))',
                content,
            )
            for e in entities:
                name = e[0] or e[1]
                if name and name not in recent_entities:
                    recent_entities.append(name)
            if recent_entities:
                break

    # Check conversation state for active topic/entities
    if conversation_state:
        active_topic = getattr(conversation_state, "active_topic", "")
        if active_topic and active_topic not in query:
            recent_entities.insert(0, active_topic)

    if not recent_entities:
        return query

    # Append resolved context as a terse suffix
    context_hint = "; ".join(recent_entities[:3])
    return f"{query}（前文涉及: {context_hint}）"
