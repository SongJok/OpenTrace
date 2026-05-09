"""
Evolution Memory Router — MemoryRouter + Compressor + Evolution + Reinforcement.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from infra.config.settings import settings
from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from memory.evolution.evolution import (
    MemoryCompressor,
    MemoryEvolution,
    MemoryReinforcement,
    MemorySkill,
)
from memory.memory_router.router import MemoryChunk, MemoryRouter

logger = get_logger(__name__)
tracer = get_tracer(__name__)


class EvolutionMemoryRouter(MemoryRouter):
    """
    Upgraded MemoryRouter with four added layers:
      1. store() — reinforcement on every write
      2. evolve_cycle() — Case→Pattern→Skill every N interactions
      3. compress_session() — compress old memories to save tokens
      4. skill_retrieve() — inject matching skills into context
    """

    _EVOLVE_THRESHOLD = 20  # auto-evolve after this many cases

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.compressor = MemoryCompressor()
        self.evolution = MemoryEvolution()
        self.reinforcement = MemoryReinforcement()
        self._pending_cases: list[dict[str, Any]] = []
        self._cached_skills: list[MemorySkill] = []

    # ------------------------------------------------------------------
    # Override store() to add reinforcement + case accumulation
    # ------------------------------------------------------------------
    async def store(  # type: ignore[override]
        self,
        session_id: str,
        query: str,
        answer: str,
        metadata: Optional[dict[str, Any]] = None,
        score: float = 0.8,
        success: bool = True,
    ) -> None:
        chunk_id = str(uuid.uuid4())
        content = f"Q: {query}\nA: {answer}"
        meta = {"session_id": session_id, "score": score, **(metadata or {})}

        try:
            await self.semantic_store.add(chunk_id, content, meta)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Semantic store failed", error=str(exc))

        await self.reinforcement.reinforce(chunk_id, success=success)

        self._pending_cases.append({
            "query": query, "response": answer,
            "score": score, "chunk_id": chunk_id,
        })

        if len(self._pending_cases) >= self._EVOLVE_THRESHOLD:
            import asyncio
            asyncio.create_task(self._run_evolution())

        logger.debug("Memory stored", session=session_id, chunk_id=chunk_id)

    async def _run_evolution(self) -> None:
        cases = list(self._pending_cases)
        self._pending_cases.clear()
        try:
            _pattern, skill = await self.evolution.evolve(cases)
            if skill:
                self._cached_skills.append(skill)
                logger.info("New skill evolved", skill=skill.name,
                            triggers=skill.trigger_conditions)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Evolution cycle failed", error=str(exc))

    # ------------------------------------------------------------------
    # Skill retrieval — inject matching skills as high-priority context
    # ------------------------------------------------------------------
    async def skill_retrieve(self, query: str) -> list[MemorySkill]:
        q = query.lower()
        if not self._cached_skills:
            _, self._cached_skills = await self.evolution.load_all()
        matches: list[MemorySkill] = []
        for skill in self._cached_skills:
            if any(cond.lower() in q for cond in skill.trigger_conditions):
                w = await self.reinforcement.get_weight(skill.skill_id)
                if w > 0.1:
                    skill.weight = w
                    matches.append(skill)
        matches.sort(key=lambda s: s.weight, reverse=True)
        return matches[:3]

    # ------------------------------------------------------------------
    # Retrieve — injects skills at the front of results, with auto-decay
    # ------------------------------------------------------------------
    async def retrieve(
        self,
        query: str,
        episodic_chunks: Optional[list[str]] = None,
        keyword_chunks: Optional[list[str]] = None,
        top_k: int = 8,
    ) -> list[MemoryChunk]:
        chunks = await super().retrieve(
            query=query,
            episodic_chunks=episodic_chunks,
            keyword_chunks=keyword_chunks,
            top_k=top_k,
        )

        # ── Feature ③: Auto-decay memories with no feedback ──
        if bool(getattr(settings, "kernel_memory_value_scoring_enabled", True)):
            decay_threshold = int(getattr(settings, "kernel_memory_auto_decay_threshold", 3))
            for chunk in chunks:
                chunk_id = chunk.metadata.get("chunk_id") or chunk.metadata.get("id")
                if chunk_id:
                    try:
                        no_fb_streak = await self._get_no_feedback_streak(chunk_id)
                        if no_fb_streak >= decay_threshold:
                            chunk.score *= 0.1  # Auto-decay
                            chunk.metadata["auto_decayed"] = True
                    except Exception:
                        pass
        # ── End auto-decay ──────────────────────────────────

        skills = await self.skill_retrieve(query)
        for skill in reversed(skills):
            chunks.insert(0, MemoryChunk(
                content=(
                    f"[SKILL:{skill.name}] {skill.description}\n"
                    f"Strategy: {skill.action_template}"
                ),
                score=skill.weight,
                source="skill",
                metadata={"skill_id": skill.skill_id},
            ))
        return chunks[:top_k + len(skills)]

    async def _get_no_feedback_streak(self, chunk_id: str) -> int:
        """Get consecutive no-feedback streak from Redis."""
        try:
            from infra.storage.redis_client import get_redis
            redis = await get_redis()
            key = f"opentrace:memory:feedback:{chunk_id}:streak"
            val = await redis.get(key)
            return int(val) if val else 0
        except Exception:
            return 0

    async def _increment_no_feedback_streak(self, chunk_id: str) -> None:
        """Increment the no-feedback streak counter."""
        try:
            from infra.storage.redis_client import get_redis
            redis = await get_redis()
            key = f"opentrace:memory:feedback:{chunk_id}:streak"
            await redis.incr(key)
            await redis.expire(key, 86400 * 30)  # 30-day TTL
        except Exception:
            pass

    async def record_feedback(self, chunk_id: str, feedback_type: str) -> None:
        """Record explicit feedback and reset streak."""
        try:
            from infra.storage.redis_client import get_redis
            redis = await get_redis()
            streak_key = f"opentrace:memory:feedback:{chunk_id}:streak"
            fb_key = f"opentrace:memory:feedback:{chunk_id}:type"
            if feedback_type in ("like", "dislike"):
                await redis.set(fb_key, feedback_type, ex=86400 * 30)
                await redis.delete(streak_key)  # Reset streak on feedback
            else:
                await self._increment_no_feedback_streak(chunk_id)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Compression
    # ------------------------------------------------------------------
    async def compress_session(
        self, session_id: str, last_n: int = 30
    ) -> Optional[str]:
        """Compress the most recent N memories of a session."""
        chunks = await super().retrieve(query="session summary", top_k=last_n)
        session_texts = [
            c.content for c in chunks
            if c.metadata.get("session_id") == session_id
        ]
        if not session_texts:
            return None
        compressed = await self.compressor.compress(session_texts)
        await super().store(
            session_id=session_id,
            query="[compressed_summary]",
            answer=compressed,
            metadata={"type": "compressed"},
        )
        logger.info("Session compressed", session=session_id,
                    from_n=len(session_texts))
        return compressed
