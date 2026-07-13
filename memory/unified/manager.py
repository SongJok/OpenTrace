"""
Unified Memory Manager - 统一记忆管理器

管理所有类型的记忆，提供统一的接口：
- 对话缓冲区管理
- 摘要生成
- 实体提取和跟踪
- 语义记忆存储和检索
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from infra.config.settings import settings
from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

from .models import (
    ConversationTurn,
    ConversationBuffer,
    MemorySummary,
    EntityMemory,
    SemanticMemory,
    MemoryContext,
    MemoryEntry,
    MemoryType,
    MemoryImportance,
)

logger = get_logger(__name__)
tracer = get_tracer(__name__)


class UnifiedMemoryManager:
    """
    统一记忆管理器
    
    协调各类记忆的管理，提供统一接口
    """

    def __init__(self):
        self._storage = {}
        self._redis_client = None
        self._retriever = None
        self._summarizer = None
        # 内存缓存
        self._buffer_cache: Dict[str, ConversationBuffer] = {}

    def _get_retriever(self):
        if self._retriever is None:
            from .retriever import MemoryRetriever
            self._retriever = MemoryRetriever()
        return self._retriever

    def _get_redis_client(self):
        if self._redis_client is None:
            from infra.storage.redis import get_redis_client
            self._redis_client = get_redis_client()
        return self._redis_client

    async def save_turn(
        self,
        session_id: str,
        user_id: Optional[str],
        query: str,
        response: str,
        tool_calls: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None
    ) -> ConversationTurn:
        """
        保存对话轮次
        """
        # 创建对话轮次
        turn = ConversationTurn(
            session_id=session_id,
            user_query=query,
            assistant_response=response,
            tools_used=[tc.get("tool_name", "unknown") for tc in (tool_calls or [])],
            metadata=metadata or {}
        )

        # 更新缓冲区缓存
        buffer = self._buffer_cache.get(session_id)
        if buffer is None:
            buffer = ConversationBuffer(session_id=session_id, user_id=user_id)
            self._buffer_cache[session_id] = buffer
        
        buffer.add_turn(turn)

        # 异步保存到持久存储
        asyncio.create_task(self._persist_turn(session_id, turn))

        # 异步触发实体提取
        asyncio.create_task(self._extract_entities(turn, user_id))
        
        # 检查是否需要摘要
        asyncio.create_task(self._check_and_trigger_summary(session_id))

        return turn

    async def _persist_turn(self, session_id: str, turn: ConversationTurn) -> None:
        """持久化对话轮次到 Redis"""
        try:
            redis = self._get_redis_client()
            buffer_key = f"conversation_buffer:{session_id}"
            
            # JSON 序列化
            turn_data = {
                "id": turn.id,
                "session_id": turn.session_id,
                "turn_number": turn.turn_number,
                "user_query": turn.user_query,
                "assistant_response": turn.assistant_response,
                "tools_used": turn.tools_used,
                "timestamp": turn.timestamp.isoformat(),
                "metadata": turn.metadata
            }
            
            await redis.lpush(buffer_key, json.dumps(turn_data))
            await redis.ltrim(buffer_key, 0, 49)  # 保留最近50轮
            
            logger.debug(f"Persisted turn for session {session_id}")
        except Exception as e:
            logger.warning(f"Failed to persist turn: {e}")

    async def retrieve_relevant(
        self,
        query: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        检索相关记忆
        """
        with tracer.start_as_current_span("memory.retrieve") as span:
            span.set_attribute("query", query)
            span.set_attribute("top_k", top_k)

            try:
                retriever = self._get_retriever()
                
                results = await retriever.retrieve(
                    query=query,
                    user_id=user_id,
                    session_id=session_id,
                    top_k=top_k
                )
                
                span.set_attribute("results_count", len(results))
                return results
            except Exception as e:
                logger.warning(f"Memory retrieval failed: {e}")
                return []

    async def get_conversation_summary(self, session_id: str) -> Optional[str]:
        """
        获取对话摘要
        """
        # 先检查缓存
        buffer = self._buffer_cache.get(session_id)
        if buffer and buffer.summary:
            return buffer.summary
        
        # 从 Redis 获取
        try:
            redis = self._get_redis_client()
            summary_key = f"conversation_summary:{session_id}"
            summary = await redis.get(summary_key)
            return summary
        except Exception as e:
            logger.warning(f"Failed to get summary: {e}")
            return None

    async def update_working_memory(
        self,
        session_id: str,
        turn_content: Dict[str, Any]
    ) -> None:
        """
        更新工作记忆
        """
        try:
            redis = self._get_redis_client()
            key = f"working_memory:{session_id}"
            
            await redis.hset(key, "last_turn", json.dumps(turn_content))
            await redis.hset(key, "last_updated", datetime.utcnow().isoformat())
        except Exception as e:
            logger.warning(f"Failed to update working memory: {e}")

    async def get_memory_context(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        query: str = ""
    ) -> MemoryContext:
        """
        获取完整记忆上下文
        """
        context = MemoryContext()

        # 1. 获取最近对话（优先从缓存）
        buffer = self._buffer_cache.get(session_id)
        if buffer:
            context.recent_turns = buffer.get_recent_turns(10)
        else:
            context.recent_turns = await self._get_recent_turns(session_id, n=10)

        # 2. 获取对话摘要
        context.conversation_summary = await self.get_conversation_summary(session_id)

        # 3. 检索相关记忆
        if query:
            try:
                relevant = await self.retrieve_relevant(
                    query=query,
                    user_id=user_id,
                    session_id=session_id,
                    top_k=5
                )
                # 转换为SemanticMemory对象
                context.relevant_memories = [
                    SemanticMemory(
                        title=mem.get("title", ""),
                        content=mem.get("content", ""),
                        **{k: v for k, v in mem.items() if k not in ['title', 'content']}
                    ) for mem in relevant if isinstance(mem, dict)
                ]
            except Exception as e:
                logger.warning(f"Failed to retrieve relevant memories: {e}")

        # 4. 获取相关实体
        context.relevant_entities = await self._get_recent_entities(session_id, n=5)

        return context

    async def store_semantic_memory(
        self,
        content: str,
        title: str = "",
        user_id: Optional[str] = None,
        knowledge_type: str = "fact",
        confidence: float = 1.0,
        source: str = "conversation",
        workspace_id: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> SemanticMemory:
        """
        存储语义记忆
        """
        memory = SemanticMemory(
            title=title or content[:50],
            content=content,
            knowledge_type=knowledge_type,
            confidence=confidence,
            source=source,
            user_id=user_id,
            workspace_id=workspace_id,
            tags=tags or []
        )

        try:
            # 保存到数据库（异步）
            asyncio.create_task(self._save_semantic_memory(memory))
            logger.info(f"Stored semantic memory: {memory.title}")
        except Exception as e:
            logger.warning(f"Failed to store semantic memory: {e}")

        return memory

    async def _save_semantic_memory(self, memory: SemanticMemory) -> None:
        """保存语义记忆到数据库"""
        try:
            # TODO: 实现数据库持久化
            # from infra.storage.database import get_db_session
            # async with get_db_session() as session:
            #     session.add(memory)
            #     await session.commit()
            pass
        except Exception as e:
            logger.warning(f"Failed to persist semantic memory: {e}")

    async def _get_recent_turns(self, session_id: str, n: int = 10) -> List[ConversationTurn]:
        """
        获取最近对话轮次
        """
        try:
            redis = self._get_redis_client()
            buffer_key = f"conversation_buffer:{session_id}"
            
            turns_data = await redis.lrange(buffer_key, 0, n - 1)
            
            turns = []
            for data in turns_data:
                try:
                    turn_dict = json.loads(data)
                    # 转换时间戳
                    if "timestamp" in turn_dict and isinstance(turn_dict["timestamp"], str):
                        turn_dict["timestamp"] = datetime.fromisoformat(turn_dict["timestamp"])
                    turn = ConversationTurn(**turn_dict)
                    turns.append(turn)
                except Exception as e:
                    logger.debug(f"Failed to parse turn data: {e}")
                    continue
            
            return turns[::-1]  # 反转，让最早的在前
        except Exception as e:
            logger.warning(f"Failed to get recent turns: {e}")
            return []

    async def _get_recent_entities(self, session_id: str, n: int = 5) -> List[EntityMemory]:
        """
        获取最近提及的实体
        """
        try:
            redis = self._get_redis_client()
            key = f"entities:{session_id}"
            entities_data = await redis.lrange(key, 0, n - 1)
            
            entities = []
            for data in entities_data:
                try:
                    entity_dict = json.loads(data)
                    if "first_mentioned_at" in entity_dict:
                        entity_dict["first_mentioned_at"] = datetime.fromisoformat(
                            entity_dict["first_mentioned_at"]
                        )
                    entity = EntityMemory(**entity_dict)
                    entities.append(entity)
                except Exception:
                    continue
            
            return entities
        except Exception as e:
            logger.debug(f"Failed to get entities: {e}")
            return []

    async def _extract_entities(self, turn: ConversationTurn, user_id: Optional[str]) -> None:
        """
        从对话中提取实体（异步）
        """
        try:
            # 简单的实体提取（可替换为 NER 模型）
            import re
            text = f"{turn.user_query} {turn.assistant_response}"
            
            # 提取可能的实体（大写字母开头的连续词）
            # 这是一个简化的实现
            potential_entities = re.findall(r'[A-Z][a-zA-Z]+', text)
            
            if potential_entities:
                redis = self._get_redis_client()
                key = f"entities:{turn.session_id}"
                for entity_name in potential_entities[:5]:  # 限制数量
                    entity = EntityMemory(
                        name=entity_name,
                        entity_type="unknown",
                        first_mentioned_in=turn.session_id
                    )
                    await redis.lpush(key, json.dumps(entity.to_dict()))
                    await redis.ltrim(key, 0, 99)  # 保留最多100个
                    
        except Exception as e:
            logger.debug(f"Entity extraction failed: {e}")

    async def _check_and_trigger_summary(self, session_id: str) -> None:
        """
        检查并触发摘要生成
        """
        try:
            buffer = self._buffer_cache.get(session_id)
            if buffer and len(buffer.turns) >= 20:
                asyncio.create_task(self._generate_summary(session_id))
        except Exception as e:
            logger.debug(f"Summary check failed: {e}")

    async def _generate_summary(self, session_id: str) -> None:
        """
        生成对话摘要（异步）
        """
        try:
            buffer = self._buffer_cache.get(session_id)
            if not buffer or len(buffer.turns) < 10:
                return

            # 使用 LLM 生成摘要
            try:
                from model.model_gateway.gateway import get_model_gateway, LLMRole
                gateway = get_model_gateway()
                
                # 构建对话文本
                conversation = []
                for turn in buffer.turns[-20:]:  # 取最近20轮
                    conversation.append(f"用户: {turn.user_query[:100]}")
                    conversation.append(f"助手: {turn.assistant_response[:100]}")
                
                messages = [
                    {
                        "role": "system",
                        "content": "请用一句话简要概括以下对话的主要内容（不超过50字）："
                    },
                    {
                        "role": "user",
                        "content": "\n".join(conversation)
                    }
                ]
                
                response = await gateway.complete(
                    messages=messages,
                    role=LLMRole.COMPRESS,
                    temperature=0.3,
                    max_tokens=100
                )
                
                summary = response.content.strip()[:200]
                buffer.summary = summary
                
                # 保存到 Redis
                redis = self._get_redis_client()
                await redis.set(f"conversation_summary:{session_id}", summary)
                
                logger.info(f"Generated summary for session {session_id}")
                
            except Exception as e:
                logger.warning(f"LLM summary generation failed: {e}")
                # 降级：使用简单摘要
                buffer.summary = f"对话共{len(buffer.turns)}轮，涉及多个主题讨论"
            
        except Exception as e:
            logger.warning(f"Summary generation failed: {e}")

    async def clear_session(self, session_id: str) -> None:
        """
        清空会话记忆
        """
        try:
            # 清除缓存
            if session_id in self._buffer_cache:
                del self._buffer_cache[session_id]
            
            # 清除 Redis
            redis = self._get_redis_client()
            await redis.delete(f"conversation_buffer:{session_id}")
            await redis.delete(f"conversation_summary:{session_id}")
            await redis.delete(f"working_memory:{session_id}")
            await redis.delete(f"entities:{session_id}")
            
            logger.info(f"Cleared memory for session {session_id}")
        except Exception as e:
            logger.warning(f"Failed to clear session memory: {e}")
    
    async def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """获取会话统计信息"""
        try:
            buffer = self._buffer_cache.get(session_id)
            redis = self._get_redis_client()
            
            buffer_len = await redis.llen(f"conversation_buffer:{session_id}")
            
            return {
                "session_id": session_id,
                "cached_turns": len(buffer.turns) if buffer else 0,
                "persisted_turns": buffer_len,
                "has_summary": buffer.summary is not None if buffer else False,
                "last_updated": buffer.updated_at.isoformat() if buffer else None
            }
        except Exception as e:
            logger.warning(f"Failed to get session stats: {e}")
            return {"session_id": session_id, "error": str(e)}
