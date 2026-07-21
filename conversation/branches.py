"""
Conversation Branches - 会话分支系统

参考ChatGPT的对话分叉功能：
1. 从任意消息创建分支
2. 保留分支历史
3. 分支间切换
4. 可视化对话树
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MessageNode:
    """消息节点"""
    id: str
    role: str  # user, assistant
    content: str
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    branch_id: str = "main"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationBranch:
    """会话分支"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    root_message_id: Optional[str] = None  # 分支起点消息ID
    parent_branch_id: Optional[str] = None
    message_ids: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = False


class ConversationTree:
    """会话树管理"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: Dict[str, MessageNode] = {}
        self.branches: Dict[str, ConversationBranch] = {}
        self.current_branch_id: str = "main"
        
        # 创建主分支
        self.branches["main"] = ConversationBranch(
            id="main",
            name="主分支"
        )
    
    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None) -> MessageNode:
        """添加消息到当前分支"""
        # 获取当前分支的最后一条消息
        current_branch = self.branches[self.current_branch_id]
        parent_id = current_branch.message_ids[-1] if current_branch.message_ids else None
        
        message = MessageNode(
            id=str(uuid.uuid4()),
            role=role,
            content=content,
            parent_id=parent_id,
            branch_id=self.current_branch_id,
            metadata=metadata or {}
        )
        
        self.messages[message.id] = message
        
        # 更新父节点的子节点
        if parent_id:
            parent = self.messages.get(parent_id)
            if parent:
                parent.children_ids.append(message.id)
        
        # 添加到当前分支
        current_branch.message_ids.append(message.id)
        
        return message
    
    def create_branch(self, from_message_id: str, name: str) -> ConversationBranch:
        """从指定消息创建新分支"""
        if from_message_id not in self.messages:
            raise ValueError(f"Message {from_message_id} not found")
        
        source_message = self.messages[from_message_id]
        source_branch = self.branches.get(source_message.branch_id)
        
        branch = ConversationBranch(
            id=str(uuid.uuid4()),
            name=name,
            root_message_id=from_message_id,
            parent_branch_id=source_message.branch_id,
            message_ids=self._get_ancestor_messages(from_message_id)
        )
        
        self.branches[branch.id] = branch
        
        logger.info(f"Branch created: {branch.id} from message {from_message_id}")
        return branch
    
    def _get_ancestor_messages(self, message_id: str) -> List[str]:
        """获取消息的所有祖先消息ID"""
        ancestors = []
        current_id = message_id
        
        while current_id:
            ancestors.insert(0, current_id)
            message = self.messages.get(current_id)
            if message:
                current_id = message.parent_id
            else:
                break
        
        return ancestors
    
    def switch_branch(self, branch_id: str) -> bool:
        """切换到指定分支"""
        if branch_id not in self.branches:
            return False
        
        # 取消当前分支激活
        self.branches[self.current_branch_id].is_active = False
        
        # 激活新分支
        self.current_branch_id = branch_id
        self.branches[branch_id].is_active = True
        
        return True
    
    def get_branch_history(self, branch_id: Optional[str] = None) -> List[MessageNode]:
        """获取分支的对话历史"""
        branch_id = branch_id or self.current_branch_id
        branch = self.branches.get(branch_id)
        
        if not branch:
            return []
        
        return [self.messages[mid] for mid in branch.message_ids if mid in self.messages]
    
    def get_tree_structure(self) -> Dict[str, Any]:
        """获取会话树的结构（用于可视化）"""
        return {
            "session_id": self.session_id,
            "current_branch": self.current_branch_id,
            "branches": [
                {
                    "id": b.id,
                    "name": b.name,
                    "parent_branch": b.parent_branch_id,
                    "message_count": len(b.message_ids),
                    "is_active": b.is_active
                }
                for b in self.branches.values()
            ],
            "total_messages": len(self.messages)
        }
