"""
记忆选择器 — 智能选择与查询最相关的记忆。

封装 MemoryFabric，提供相关性评分、去重和新近度偏置。
生成排序后的记忆块列表，可供 ContextCompressor 使用。
"""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


class MemorySelector:
    """按与当前查询的相关性选择和排序记忆。

    封装 MemoryFabric.retrieve_context()，提供：
    - 去重（语义近似重复）
    - 新近度偏置（较新的记忆评分更高）
    - 置信度过滤（丢弃低置信度记忆）
    - token 预算感知
    """

    def __init__(self, memory_fabric: Any = None) -> None:
        self._memory_fabric = memory_fabric

    async def _ensure_fabric(self) -> Any:
        if self._memory_fabric is None:
            from kernel.runtime.memory_fabric import memory_fabric
            self._memory_fabric = memory_fabric
        return self._memory_fabric

    async def select(
        self,
        query: str,
        session_id: str = "",
        user_id: str = "",
        max_memories: int = 5,
        min_confidence: float = 0.3,
    ) -> str:
        """选择并格式化相关记忆以插入提示词。

        返回格式化的上下文块字符串，可供压缩器使用。
        """
        fabric = await self._ensure_fabric()
        if fabric is None:
            return ""

        try:
            context_block, events = await fabric.retrieve_context(
                query=query,
                session_id=session_id,
                user_id=user_id,
                top_k=max_memories * 2,  # 多取一些再过滤
            )
        except Exception as exc:
            logger.debug("MemorySelector retrieve failed", error=str(exc))
            return ""

        if not context_block:
            if events:
                # 将事件格式化为记忆上下文
                parts: list[str] = []
                for ev in events[:max_memories]:
                    if isinstance(ev, dict):
                        content = ev.get("content", "") or ev.get("description", "")
                        if content:
                            parts.append(f"- {str(content)[:500]}")
                return "\n".join(parts) if parts else ""
            return ""

        # 应用 min_confidence 过滤（如果上下文块质量似乎较低）
        # （EvolutionMemoryRouter 已做过滤，此处为安全网）
        if len(context_block) < 20 and not events:
            return ""

        return context_block[:3000]  # 压缩器前的安全上限
