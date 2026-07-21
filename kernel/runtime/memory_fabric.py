"""
MemoryFabric — EvolutionMemoryRouter 的统一读写封装。

为编排器提供单一 API 来读取（检索上下文）和写入（记录事件、保存记忆），
无需了解底层记忆实现细节。
"""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


class MemoryFabric:
    """统一记忆访问层。

    封装 EvolutionMemoryRouter，为编排器提供简化接口。
    处理：工作记忆、语义召回、情景记录和偏好更新。
    """

    def __init__(self) -> None:
        self._router: Any = None

    async def _ensure_router(self) -> Any:
        if self._router is None:
            try:
                from memory.evolution_memory_router import EvolutionMemoryRouter

                self._router = EvolutionMemoryRouter()
            except ImportError:
                logger.warning("EvolutionMemoryRouter not available, memory fabric disabled")
                self._router = False
        return self._router if self._router is not False else None

    async def retrieve_context(
        self,
        query: str,
        session_id: str = "",
        user_id: str = "",
        top_k: int = 5,
    ) -> tuple[str, list[dict[str, Any]]]:
        """检索与查询相关的记忆上下文。

        返回 (格式化上下文块, 情景事件列表)。
        """
        router = await self._ensure_router()
        if router is None:
            return "", []

        try:
            result = await router.retrieve(
                query=query,
                session_id=session_id,
                user_id=user_id,
                top_k=top_k,
            )
            context_block = getattr(result, "formatted_context", "") or ""
            events = getattr(result, "episodic_events", []) or []
            return context_block, events
        except Exception as exc:
            logger.warning("MemoryFabric retrieve failed", error=str(exc))
            return "", []

    async def record_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        session_id: str = "",
    ) -> None:
        """记录会话的情景事件。"""
        router = await self._ensure_router()
        if router is None:
            return

        try:
            if hasattr(router, "record_event"):
                await router.record_event(
                    event_type=event_type,
                    payload=payload,
                    session_id=session_id,
                )
        except Exception as exc:
            logger.debug("MemoryFabric record_event failed", error=str(exc))

    async def save_preference(self, user_id: str, key: str, value: Any) -> None:
        """持久化用户偏好。"""
        router = await self._ensure_router()
        if router is None:
            return

        try:
            if hasattr(router, "save_preference"):
                await router.save_preference(user_id, key, value)
        except Exception as exc:
            logger.debug("MemoryFabric save_preference failed", error=str(exc))

    # ── 治理 API ──────────────────────────────────────────────────────

    def check_contradiction(
        self, new_content: str, existing_contents: list[str]
    ) -> list[tuple[str, float]]:
        """检查新内容是否与已有记忆矛盾。"""
        try:
            from memory.evolution.governance import memory_governance
            return memory_governance.check_contradiction(new_content, existing_contents)
        except Exception as exc:
            logger.warning("memory_fabric_contradiction_check_failed", error=str(exc))
            return []

    def decay_confidence(self, chunk_id: str) -> float:
        """Apply confidence decay and return current score."""
        try:
            from memory.evolution.governance import memory_governance
            return memory_governance.apply_decay(chunk_id)
        except Exception as exc:
            logger.warning("memory_fabric_decay_failed", chunk_id=chunk_id, error=str(exc))
            return 0.5

    def get_provenance(self, chunk_id: str) -> Any | None:
        """Get provenance for a memory chunk."""
        try:
            from memory.evolution.governance import memory_governance
            return memory_governance.get_provenance(chunk_id)
        except Exception as exc:
            logger.warning("memory_fabric_provenance_get_failed", chunk_id=chunk_id, error=str(exc))
            return None

    def track_provenance(
        self,
        chunk_id: str,
        source_agent: str = "",
        session_id: str = "",
        turn_index: int = 0,
        original_query: str = "",
    ) -> None:
        """Record provenance for a memory chunk."""
        try:
            from memory.evolution.governance import memory_governance
            memory_governance.track_provenance(
                chunk_id=chunk_id,
                source_agent=source_agent,
                session_id=session_id,
                turn_index=turn_index,
                original_query=original_query,
            )
        except Exception as exc:
            logger.warning(
                "memory_fabric_provenance_track_failed",
                chunk_id=chunk_id,
                error=str(exc),
            )


# Module-level singleton — follow capability_registry pattern
memory_fabric = MemoryFabric()
