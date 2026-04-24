from __future__ import annotations

import re
from typing import Any

from infra.config.settings import settings
from model.model_gateway.gateway import LLMRole, get_model_gateway


class QueryRewriter:
    """Query rewrite for recall robustness and quality improvement."""

    async def rewrite(self, query: str) -> str:
        q = (query or "").strip()
        if not q:
            return q
        # 先做最小实现：去多空格与常见前缀噪声
        q = " ".join(q.split())
        for prefix in ["请你", "麻烦", "帮我"]:
            if q.startswith(prefix):
                q = q[len(prefix):].strip()
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
            all_terms = orig_terms + chunk_only[:max_terms - len(orig_terms)]

        # Build improved query
        improved = " ".join(all_terms)

        # If LLM query refinement is enabled and we have enough context
        if getattr(settings, "enable_llm_query_refinement", False) and rag_chunks:
            try:
                improved = await self._llm_refine_query(
                    original_query, rag_chunks[:2], improved
                )
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
