from __future__ import annotations

from typing import Any

import numpy as np


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    a_arr = np.array(a, dtype=np.float32)
    b_arr = np.array(b, dtype=np.float32)
    na = float(np.linalg.norm(a_arr))
    nb = float(np.linalg.norm(b_arr))
    if na < 1e-8 or nb < 1e-8:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (na * nb))


class ContextRanker:
    """Heuristic context ranking with MMR dedup."""

    def rank(
        self,
        chunks: list[Any],
        top_k: int = 8,
        mmr_lambda: float = 0.7,
    ) -> list[Any]:
        if not chunks:
            return []
        # Sort by score descending
        scored = sorted(
            chunks,
            key=lambda c: float(getattr(c, "score", 0.0)),
            reverse=True,
        )
        if not mmr_lambda or mmr_lambda >= 1.0 or len(scored) <= 1:
            return scored[:top_k]

        # MMR: greedily select chunks balancing relevance and diversity
        selected: list[Any] = [scored[0]]
        remaining = scored[1:]

        while len(selected) < min(top_k, len(chunks)):
            best_score = -float("inf")
            best_idx = -1
            for i, chunk in enumerate(remaining):
                relevance = float(getattr(chunk, "score", 0.0))
                # Diversity: max similarity to any already-selected chunk
                sims = []
                for sel in selected:
                    sel_emb = getattr(sel, "embedding", None) or []
                    chunk_emb = getattr(chunk, "embedding", None) or []
                    if sel_emb and chunk_emb:
                        sims.append(_cosine_sim(list(sel_emb), list(chunk_emb)))
                max_sim = max(sims) if sims else 0.0
                mmr = mmr_lambda * relevance - (1 - mmr_lambda) * max_sim
                if mmr > best_score:
                    best_score = mmr
                    best_idx = i
            if best_idx < 0:
                break
            selected.append(remaining.pop(best_idx))

        return selected
