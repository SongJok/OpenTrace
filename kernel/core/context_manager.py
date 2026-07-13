"""
上下文管理器 - 智能上下文窗口管理

参考 ChatGPT 的上下文管理策略：
1. 滑动窗口保留最近对话
2. 关键信息提取与压缩
3. 长对话摘要机制
4. 跨会话记忆检索
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
import json

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


@dataclass
class ContextWindow:
    """上下文窗口"""
    messages: List[Dict[str, str]] = field(default_factory=list)
    system_prompt: str = ""
    token_count: int = 0
    summary: Optional[str] = None
    key_facts: List[str] = field(default_factory=list)
    relevant_memories: List[Dict] = field(default_factory=list)
    entities: List[Dict] = field(default_factory=list)
    
    def to_llm_messages(self) -> List[Dict[str, str]]:
        """转换为 LLM 消息格式"""
        messages = [{"role": "system", "content": self.system_prompt}]
        
        # 如果有摘要，插入为上下文
        if self.summary:
            messages.append({
                "role": "system",
                "content": f"[对话摘要] {self.summary}"
            })
        
        # 添加关键事实
        if self.key_facts:
            facts = "\n".join(f"- {f}" for f in self.key_facts[:10])
            messages.append({
                "role": "system",
                "content": f"[关键信息]\n{facts}"
            })
        
        # 添加相关记忆
        if self.relevant_memories:
            memories_text = self._format_memories()
            if memories_text:
                messages.append({
                    "role": "system",
                    "content": f"[相关记忆]\n{memories_text}"
                })
        
        # 添加用户消息
        messages.extend(self.messages)
        
        return messages
    
    def _format_memories(self) -> str:
        """格式化记忆为文本"""
        lines = []
        for mem in self.relevant_memories[:5]:  # 最多5条
            if isinstance(mem, dict):
                title = mem.get("title", "")
                content = mem.get("content", "")
                if title and content:
                    lines.append(f"- {title}: {content[:100]}...")
                elif content:
                    lines.append(f"- {content[:150]}...")
        return "\n".join(lines)


class ContextManager:
    """
    智能上下文管理器
    
    实现：
    - 滑动窗口管理
    - 智能压缩策略
    - 动态摘要生成
    - 记忆检索整合
    """
    
    MAX_TOKENS = 6000  # 预留 2000 tokens 给回复
    SUMMARY_TRIGGER = 10  # 10轮对话后触发摘要
    CHUNK_SIZE = 4  # 中文分块大小
    
    def __init__(self):
        self._memory_manager = None
        self._session_contexts: Dict[str, Dict] = {}
    
    def _get_memory_manager(self):
        if self._memory_manager is None:
            from memory.unified.manager import UnifiedMemoryManager
            self._memory_manager = UnifiedMemoryManager()
        return self._memory_manager
    
    async def build_context(
        self,
        session_id: str,
        user_id: str,
        current_query: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> ContextWindow:
        """
        构建优化后的上下文窗口
        """
        with tracer.start_as_current_span("context.build") as span:
            span.set_attribute("session_id", session_id)
            span.set_attribute("query", current_query[:50])
            
            # 1. 获取会话记忆上下文
            memory_manager = self._get_memory_manager()
            memory_context = await memory_manager.get_memory_context(
                session_id=session_id,
                user_id=user_id,
                query=current_query
            )
            
            # 2. 构建系统提示词
            system_prompt = self._build_system_prompt(memory_context, current_query)
            
            # 3. 处理对话历史
            processed_messages = self._process_history(
                conversation_history or [],
                memory_context
            )
            
            # 4. 计算 token 使用
            token_count = self._estimate_tokens(processed_messages, system_prompt)
            
            # 5. 如果超出限制，进行压缩
            if token_count > self.MAX_TOKENS:
                processed_messages, summary = await self._compress_context(
                    processed_messages,
                    memory_context
                )
                token_count = self._estimate_tokens(processed_messages, system_prompt)
            else:
                summary = None
            
            # 6. 提取关键信息
            key_facts = self._extract_key_facts(memory_context)
            
            # 7. 格式化相关记忆
            relevant_memories = []
            if hasattr(memory_context, "relevant_memories"):
                relevant_memories = [
                    m.to_dict() if hasattr(m, "to_dict") else m
                    for m in memory_context.relevant_memories
                ]
            
            context = ContextWindow(
                messages=processed_messages,
                system_prompt=system_prompt,
                token_count=token_count,
                summary=summary or getattr(memory_context, "conversation_summary", None),
                key_facts=key_facts,
                relevant_memories=relevant_memories
            )
            
            span.set_attribute("token_count", token_count)
            span.set_attribute("message_count", len(processed_messages))
            
            return context
    
    def _build_system_prompt(
        self,
        memory_context,
        current_query: str
    ) -> str:
        """构建动态系统提示词"""
        base_prompt = """你是 OpenTrace，一个先进的 AI 助手。你具备以下能力：
- 理解复杂问题并进行深度推理
- 使用工具获取实时信息
- 管理记忆和上下文
- 支持多轮对话和分支管理"""
        
        # 根据查询类型调整提示词
        if any(kw in current_query.lower() for kw in ["代码", "program", "code", "python"]):
            base_prompt += "\n\n在回答编程问题时，请提供清晰的代码示例和详细注释。"
        
        if any(kw in current_query.lower() for kw in ["分析", "分析", "analyze", "compare"]):
            base_prompt += "\n\n在进行分析时，请结构化地呈现信息，列出关键要点。"
        
        return base_prompt
    
    def _process_history(
        self,
        history: List[Dict],
        memory_context
    ) -> List[Dict[str, str]]:
        """处理对话历史"""
        messages = []
        
        # 从 memory_context 获取最近对话
        recent_turns = []
        if hasattr(memory_context, "recent_turns"):
            recent_turns = memory_context.recent_turns
        
        # 最多保留最近10轮对话
        for turn in recent_turns[-10:]:
            if hasattr(turn, "user_query") and turn.user_query:
                messages.append({
                    "role": "user",
                    "content": turn.user_query
                })
            if hasattr(turn, "assistant_response") and turn.assistant_response:
                messages.append({
                    "role": "assistant",
                    "content": turn.assistant_response
                })
        
        return messages
    
    def _estimate_tokens(
        self,
        messages: List[Dict],
        system_prompt: str
    ) -> int:
        """估算 token 数"""
        total = len(system_prompt) // 2  # 系统提示词
        
        for msg in messages:
            content = msg.get("content", "")
            # 中文按字符，英文按单词估算
            chinese_chars = sum(1 for c in content if ord(c) > 127)
            english_words = len(content.split()) - chinese_chars
            total += chinese_chars + english_words
        
        return total

    def _check_type(self, value: Any, expected_type: str) -> bool:
        """Validate the JSON-schema primitive types used by context metadata."""
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "object":
            return isinstance(value, dict)
        if expected_type in {"null", "none"}:
            return value is None
        return False
    
    async def _compress_context(
        self,
        messages: List[Dict],
        memory_context
    ) -> tuple[List[Dict[str, str]], Optional[str]]:
        """压缩上下文"""
        if len(messages) <= 4:
            return messages, None
        
        # 保留最近的 4 条消息
        recent = messages[-4:]
        
        # 对早期的消息生成摘要
        early = messages[:-4]
        summary = await self._summarize_messages(early)
        
        return recent, summary
    
    async def _summarize_messages(
        self,
        messages: List[Dict]
    ) -> str:
        """摘要历史消息"""
        # 构建摘要文本
        conversation = []
        for msg in messages:
            role = "用户" if msg.get("role") == "user" else "助手"
            content = msg.get("content", "")[:100]  # 截断
            conversation.append(f"{role}: {content}")
        
        text = "\n".join(conversation)
        
        # 如果对话较短，直接返回要点
        if len(messages) <= 6:
            return f"之前讨论了: {text[:200]}..."
        
        # 尝试使用 LLM 生成摘要
        try:
            from model.model_gateway.gateway import get_model_gateway, LLMRole
            gateway = get_model_gateway()
            
            summary_messages = [
                {
                    "role": "system",
                    "content": "请用一句话简要概括以下对话的主要内容（不超过50字）："
                },
                {
                    "role": "user",
                    "content": text[:500]
                }
            ]
            
            response = await gateway.complete(
                messages=summary_messages,
                role=LLMRole.COMPRESS,
                temperature=0.3,
                max_tokens=100
            )
            
            return response.content.strip()[:100]
            
        except Exception as e:
            logger.warning(f"Summary generation failed: {e}")
            # 降级：使用关键词提取
            return self._extract_keywords(text)
    
    def _extract_keywords(self, text: str) -> str:
        """提取关键词作为简单摘要"""
        # 简单的关键词提取
        words = text.split()
        if len(words) <= 10:
            return text[:100]
        
        # 返回前几个词的概览
        return f"之前的对话涉及: {text[:150]}..."
    
    def _extract_key_facts(self, memory_context) -> List[str]:
        """提取关键事实"""
        facts = []
        
        # 从实体中提取
        if hasattr(memory_context, "relevant_entities"):
            for entity in memory_context.relevant_entities:
                if isinstance(entity, dict):
                    name = entity.get("name", "")
                    description = entity.get("description", "")
                    if name:
                        facts.append(f"{name}: {description[:50]}" if description else name)
        
        return facts[:5]  # 最多5个关键事实
