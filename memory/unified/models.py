"""
Memory Models - 记忆模型

定义统一记忆系统的数据模型
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class MemoryType(Enum):
    """记忆类型"""
    CONVERSATION = "conversation"  # 对话记忆
    SUMMARY = "summary"  # 摘要记忆
    ENTITY = "entity"  # 实体记忆
    SEMANTIC = "semantic"  # 语义记忆
    EPISODIC = "episodic"  # 情景记忆
    PROCEDURAL = "procedural"  # 程序性记忆


class MemoryImportance(Enum):
    """记忆重要性级别"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class MemoryEntry:
    """
    基础记忆条目
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    memory_type: MemoryType = MemoryType.SEMANTIC
    importance: MemoryImportance = MemoryImportance.MEDIUM
    
    # 关联信息
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    workspace_id: Optional[str] = None
    
    # 时间戳
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed_at: datetime = field(default_factory=datetime.utcnow)
    
    # 访问统计
    access_count: int = 0
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 向量化表示（用于语义检索）
    embedding: Optional[List[float]] = None
    
    # 标签
    tags: List[str] = field(default_factory=list)
    
    # 关联的其他记忆ID
    related_memory_ids: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        data['memory_type'] = self.memory_type.value
        data['importance'] = self.importance.value
        data['created_at'] = self.created_at.isoformat()
        data['last_accessed_at'] = self.last_accessed_at.isoformat()
        return data
    
    def mark_accessed(self):
        """标记为已访问"""
        self.access_count += 1
        self.last_accessed_at = datetime.utcnow()


@dataclass
class ConversationTurn:
    """
    对话轮次
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    turn_number: int = 0
    
    # 用户输入
    user_query: str = ""
    
    # AI响应
    assistant_response: str = ""
    
    # 使用的工具
    tools_used: List[str] = field(default_factory=list)
    
    # 推理过程
    reasoning_steps: List[Dict[str, Any]] = field(default_factory=list)
    
    # 引用的来源
    citations: List[Dict[str, Any]] = field(default_factory=list)
    
    # 时间戳
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Token统计
    input_tokens: int = 0
    output_tokens: int = 0
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationBuffer:
    """
    对话缓冲区
    
    保留最近N轮完整对话，超过部分自动摘要
    """
    session_id: str = ""
    user_id: Optional[str] = None
    
    # 完整对话历史（限制大小）
    turns: List[ConversationTurn] = field(default_factory=list)
    
    # 最大保留轮数
    max_turns: int = 20
    
    # 摘要（早期对话的压缩）
    summary: Optional[str] = None
    
    # 创建时间
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    # 最后更新时间
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def add_turn(self, turn: ConversationTurn) -> None:
        """添加新轮次"""
        turn.turn_number = len(self.turns) + 1
        turn.session_id = self.session_id
        self.turns.append(turn)
        self.updated_at = datetime.utcnow()
        
        # 如果超过限制，触发摘要
        if len(self.turns) > self.max_turns:
            self._compress_old_turns()
    
    def get_recent_turns(self, n: int = 10) -> List[ConversationTurn]:
        """获取最近n轮对话"""
        return self.turns[-n:] if len(self.turns) > n else self.turns.copy()
    
    def get_context_for_llm(self) -> List[Dict[str, str]]:
        """获取LLM格式的上下文"""
        context = []
        
        # 如果有摘要，先添加
        if self.summary:
            context.append({
                "role": "system",
                "content": f"[对话摘要] {self.summary}"
            })
        
        # 添加最近轮次
        for turn in self.turns[-10:]:  # 只取最近10轮
            context.append({
                "role": "user",
                "content": turn.user_query
            })
            context.append({
                "role": "assistant",
                "content": turn.assistant_response
            })
        
        return context
    
    def _compress_old_turns(self) -> None:
        """压缩旧轮次（应触发异步摘要任务）"""
        # 标记需要摘要，实际摘要在后台任务中完成
        if not self.summary:
            self.summary = ""  # 占位，等待摘要生成
    
    def clear(self) -> None:
        """清空对话"""
        self.turns.clear()
        self.summary = None
        self.updated_at = datetime.utcnow()


@dataclass
class MemorySummary:
    """
    记忆摘要
    
    压缩早期对话为关键信息摘要
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    
    # 摘要内容
    content: str = ""
    
    # 覆盖的轮次范围
    start_turn: int = 0
    end_turn: int = 0
    
    # 提取的关键主题
    key_topics: List[str] = field(default_factory=list)
    
    # 提取的关键决策/结论
    key_decisions: List[str] = field(default_factory=list)
    
    # 时间戳
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class EntityMemory:
    """
    实体记忆
    
    跟踪对话中提到的关键实体及其信息
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # 实体名称
    name: str = ""
    
    # 实体类型
    entity_type: str = ""  # person, organization, product, concept, etc.
    
    # 实体描述
    description: str = ""
    
    # 属性
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    # 首次提及
    first_mentioned_at: datetime = field(default_factory=datetime.utcnow)
    first_mentioned_in: Optional[str] = None
    
    # 提及次数
    mention_count: int = 1
    
    # 相关实体
    related_entities: List[str] = field(default_factory=list)
    
    # 关联用户
    user_id: Optional[str] = None
    
    def update_mention(self, session_id: str) -> None:
        """更新提及信息"""
        self.mention_count += 1


@dataclass
class SemanticMemory:
    """
    语义记忆
    
    长期存储的事实性知识，类似知识库
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # 知识标题
    title: str = ""
    
    # 知识内容
    content: str = ""
    
    # 知识类型
    knowledge_type: str = "fact"  # fact, preference, instruction, relationship
    
    # 来源
    source: str = ""  # conversation, document, user_input, etc.
    source_id: Optional[str] = None
    
    # 置信度
    confidence: float = 1.0
    
    # 关联用户
    user_id: Optional[str] = None
    
    # 关联工作区
    workspace_id: Optional[str] = None
    
    # 时间戳
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    # 有效性
    is_active: bool = True
    
    # 验证状态
    verification_status: str = "unverified"  # unverified, verified, disputed
    
    # 访问统计
    access_count: int = 0
    last_accessed_at: Optional[datetime] = None
    
    # 向量化
    embedding: Optional[List[float]] = None
    
    # 标签
    tags: List[str] = field(default_factory=list)


@dataclass
class MemoryContext:
    """
    记忆上下文
    
    为LLM提供的完整记忆上下文
    """
    # 最近对话
    recent_turns: List[ConversationTurn] = field(default_factory=list)
    
    # 对话摘要
    conversation_summary: Optional[str] = None
    
    # 相关语义记忆
    relevant_memories: List[SemanticMemory] = field(default_factory=list)
    
    # 相关实体
    relevant_entities: List[EntityMemory] = field(default_factory=list)
    
    # 用户偏好
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    
    def to_messages(self) -> List[Dict[str, str]]:
        """转换为LLM消息格式"""
        messages = []
        
        # 添加摘要
        if self.conversation_summary:
            messages.append({
                "role": "system",
                "content": f"[对话历史摘要] {self.conversation_summary}"
            })
        
        # 添加相关记忆
        for mem in self.relevant_memories[:3]:
            messages.append({
                "role": "system",
                "content": f"[相关记忆: {mem.title}] {mem.content}"
            })
        
        # 添加相关实体
        for entity in self.relevant_entities[:3]:
            messages.append({
                "role": "system",
                "content": f"[相关实体: {entity.name}] {entity.description}"
            })
        
        # 添加最近对话
        for turn in self.recent_turns:
            messages.append({
                "role": "user",
                "content": turn.user_query
            })
            messages.append({
                "role": "assistant",
                "content": turn.assistant_response
            })
        
        return messages
