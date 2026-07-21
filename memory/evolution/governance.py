"""
MemoryGovernance — Confidence decay, contradiction detection, and provenance
tracking for the memory fabric.

Prevents memory pollution by:
  1. Confidence decay: unused memories lose confidence over time
  2. Contradiction detection: flagging conflicting memories
  3. Provenance tracking: tracking source agent/session/turn for every memory
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from infra.observability.logger import get_logger

logger = get_logger(__name__)

# Half-life for confidence decay (seconds) — default 7 days
_DEFAULT_DECAY_HALF_LIFE = 86400 * 7
# Minimum confidence before a memory is considered "stale"
_MIN_CONFIDENCE_THRESHOLD = 0.15


@dataclass
class MemoryProvenance:
    """Tracks where a memory came from."""
    source_agent: str = ""       # e.g., "rag", "data", "web"
    session_id: str = ""
    turn_index: int = 0
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)
    access_count: int = 0
    original_query: str = ""


@dataclass
class MemoryConfidence:
    """Confidence score with decay tracking."""
    score: float = 0.8
    initial_score: float = 0.8
    last_updated: float = field(default_factory=time.time)
    half_life_seconds: float = _DEFAULT_DECAY_HALF_LIFE

    def decayed_score(self, now: float | None = None) -> float:
        """Apply exponential decay: score * 2^(-age / half_life)."""
        now = now or time.time()
        age = now - self.last_updated
        if age <= 0:
            return self.score
        decay_factor = 2.0 ** (-age / self.half_life_seconds)
        return self.score * decay_factor

    def refresh(self, boost: float = 0.05) -> None:
        """Refresh confidence on access, with a small boost."""
        self.score = min(1.0, self.decayed_score() + boost)
        self.last_updated = time.time()


class ContradictionDetector:
    """Detects contradictions between new and existing memories."""

    _CONTRADICT_KEY_PAIRS: list[tuple[str, str]] = [
        ("增加", "减少"), ("上升", "下降"), ("增长", "衰退"),
        ("盈利", "亏损"), ("成功", "失败"),
        ("启用", "禁用"), ("开启", "关闭"),
    ]

    def detect(
        self,
        new_content: str,
        existing_contents: list[str],
    ) -> list[tuple[str, float]]:
        """Return (conflicting_content_snippet, conflict_score) pairs."""
        conflicts: list[tuple[str, float]] = []
        new_lower = new_content.lower()

        for existing in existing_contents:
            exist_lower = existing.lower()
            score = 0.0

            # Keyword-based contradiction detection
            for kw_a, kw_b in self._CONTRADICT_KEY_PAIRS:
                if kw_a in new_lower and kw_b in exist_lower:
                    score += 0.3
                if kw_b in new_lower and kw_a in exist_lower:
                    score += 0.3

            # Numeric contradiction: detect if same entity has very different values
            score += self._numeric_contradiction_score(new_content, existing)

            if score > 0.3:
                conflicts.append((existing[:200], min(score, 1.0)))

        return conflicts

    @staticmethod
    def _numeric_contradiction_score(text_a: str, text_b: str) -> float:
        """Detect if two texts report very different numbers for the same topic."""
        import re

        # Simple heuristic: find numbers in both texts
        nums_a = re.findall(r"[\d,.]+%?", text_a)
        nums_b = re.findall(r"[\d,.]+%?", text_b)

        score = 0.0
        for na in nums_a:
            for nb in nums_b:
                try:
                    va = float(na.replace(",", "").replace("%", ""))
                    vb = float(nb.replace(",", "").replace("%", ""))
                    if va > 0 and vb > 0:
                        ratio = max(va, vb) / min(va, vb)
                        if ratio > 3.0:
                            score += 0.15
                except ValueError:
                    continue
        return min(score, 0.5)


class MemoryGovernance:
    """Central governance for the memory fabric.

    Provides confidence decay, contradiction detection, and provenance tracking
    as a unified layer that wraps the EvolutionMemoryRouter.
    """

    def __init__(self) -> None:
        self._provenance: dict[str, MemoryProvenance] = {}
        self._confidence: dict[str, MemoryConfidence] = {}
        self._contradiction_detector = ContradictionDetector()
        self._decay_half_life = float(
            getattr(__import__("infra.config.settings", fromlist=["settings"]).settings,
                     "kernel_memory_decay_half_life_seconds", _DEFAULT_DECAY_HALF_LIFE)
        ) if False else _DEFAULT_DECAY_HALF_LIFE

    # ── Confidence decay ──────────────────────────────────────────────────

    def get_confidence(self, chunk_id: str) -> MemoryConfidence:
        """Get or create confidence tracker for a memory chunk."""
        if chunk_id not in self._confidence:
            self._confidence[chunk_id] = MemoryConfidence(
                half_life_seconds=self._decay_half_life,
            )
        return self._confidence[chunk_id]

    def apply_decay(self, chunk_id: str) -> float:
        """Apply confidence decay and return current score."""
        conf = self.get_confidence(chunk_id)
        current = conf.decayed_score()
        if current < _MIN_CONFIDENCE_THRESHOLD:
            logger.debug("Memory confidence below threshold", chunk_id=chunk_id, score=current)
        return current

    def refresh_confidence(self, chunk_id: str, boost: float = 0.05) -> None:
        """Refresh confidence on access (retrieval or feedback)."""
        conf = self.get_confidence(chunk_id)
        conf.refresh(boost)

    def decay_all(self) -> dict[str, float]:
        """Apply decay to all tracked memories. Returns {chunk_id: current_score}."""
        results: dict[str, float] = {}
        for chunk_id in list(self._confidence.keys()):
            score = self.apply_decay(chunk_id)
            results[chunk_id] = score
        return results

    # ── Contradiction detection ───────────────────────────────────────────

    def check_contradiction(
        self,
        new_content: str,
        existing_contents: list[str],
    ) -> list[tuple[str, float]]:
        """Check if new content contradicts existing memories."""
        return self._contradiction_detector.detect(new_content, existing_contents)

    def resolve_contradiction(
        self,
        new_chunk_id: str,
        old_chunk_id: str,
        new_confidence: float,
        old_confidence: float,
    ) -> str:
        """Resolve a contradiction by keeping the memory with higher confidence.

        Returns the chunk_id that should be kept.
        """
        if new_confidence >= old_confidence:
            logger.debug(
                "Contradiction resolved: new memory kept",
                kept=new_chunk_id, superseded=old_chunk_id,
            )
            return new_chunk_id
        else:
            logger.debug(
                "Contradiction resolved: old memory kept",
                kept=old_chunk_id, rejected=new_chunk_id,
            )
            return old_chunk_id

    # ── Provenance tracking ───────────────────────────────────────────────

    def track_provenance(
        self,
        chunk_id: str,
        source_agent: str = "",
        session_id: str = "",
        turn_index: int = 0,
        original_query: str = "",
    ) -> MemoryProvenance:
        """Record provenance for a memory chunk."""
        prov = MemoryProvenance(
            source_agent=source_agent,
            session_id=session_id,
            turn_index=turn_index,
            original_query=original_query,
        )
        self._provenance[chunk_id] = prov
        return prov

    def get_provenance(self, chunk_id: str) -> MemoryProvenance | None:
        """Get provenance for a memory chunk."""
        return self._provenance.get(chunk_id)

    def record_access(self, chunk_id: str) -> None:
        """Record that a memory chunk was accessed."""
        prov = self._provenance.get(chunk_id)
        if prov:
            prov.last_accessed_at = time.time()
            prov.access_count += 1
        # Also refresh confidence
        self.refresh_confidence(chunk_id)

    # ── Staleness ─────────────────────────────────────────────────────────

    def get_stale_chunks(self) -> list[str]:
        """Return chunk IDs whose confidence has decayed below threshold."""
        stale: list[str] = []
        now = time.time()
        for chunk_id in list(self._confidence.keys()):
            conf = self._confidence[chunk_id]
            if conf.decayed_score(now) < _MIN_CONFIDENCE_THRESHOLD:
                stale.append(chunk_id)
        return stale

    def prune_stale(self) -> int:
        """Remove all tracked metadata for stale chunks."""
        stale = self.get_stale_chunks()
        for chunk_id in stale:
            self._provenance.pop(chunk_id, None)
            self._confidence.pop(chunk_id, None)
        if stale:
            logger.info("Pruned stale memory governance entries", count=len(stale))
        return len(stale)


# Module-level singleton
memory_governance = MemoryGovernance()
