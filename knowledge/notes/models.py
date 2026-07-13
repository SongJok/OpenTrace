"""
Knowledge Notes Models - 知识笔记模型

参考Obsidian的笔记系统：
- 笔记（Note）是基本单位
- 支持双向链接 [[Note Title]]
- 支持块级引用 ^block-id
- 支持标签 #tag
- 支持属性 ::value
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class NoteBlock:
    """
    笔记中的块（可引用单元）
    
    Obsidian风格：
    - 段落是一个块
    - 可以添加 ^block-id 进行引用
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    content: str = ""
    block_type: str = "paragraph"  # paragraph, heading, list, code, quote, etc.
    level: int = 0  # 标题级别（如果是标题）
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 嵌入ID（用于块级引用）
    embed_id: Optional[str] = None
    
    def __post_init__(self):
        if not self.embed_id and self.content:
            # 从内容中提取 ^id
            match = re.search(r'\^([a-zA-Z0-9_-]+)$', self.content.strip())
            if match:
                self.embed_id = match.group(1)


@dataclass
class BiDirectionalLink:
    """
    双向链接
    
    记录笔记之间的链接关系
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # 源笔记
    source_note_id: str = ""
    source_note_title: str = ""
    
    # 目标笔记
    target_note_id: str = ""
    target_note_title: str = ""
    
    # 链接上下文（可选，记录链接出现的位置）
    context: str = ""
    
    # 链接类型
    link_type: str = "reference"  # reference, embed, tag, backlink
    
    # 时间戳
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source_note_id,
            "source_title": self.source_note_title,
            "target": self.target_note_id,
            "target_title": self.target_note_title,
            "type": self.link_type,
            "context": self.context
        }


@dataclass
class KnowledgeNote:
    """
    知识笔记
    
    参考Obsidian的Note概念
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    content: str = ""
    
    # 所属工作区
    workspace_id: Optional[str] = None
    
    # 创建者
    user_id: str = ""
    
    # 时间戳
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    # 内容块
    blocks: List[NoteBlock] = field(default_factory=list)
    
    # 标签
    tags: Set[str] = field(default_factory=set)
    
    # 属性（Frontmatter）
    properties: Dict[str, Any] = field(default_factory=dict)
    
    # 向量化表示
    embedding: Optional[List[float]] = None
    
    # 笔记类型
    note_type: str = "note"  # note, concept, fact, procedure, insight
    
    # 状态
    status: str = "active"  # active, archived, draft
    
    # 双向链接（出链）
    outgoing_links: List[BiDirectionalLink] = field(default_factory=list)
    
    # 双向链接（入链）- 动态计算
    incoming_links: List[BiDirectionalLink] = field(default_factory=list)
    
    # 父笔记（用于层级结构）
    parent_id: Optional[str] = None
    
    # 子笔记
    children_ids: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """初始化时解析内容"""
        if self.content and not self.blocks:
            self._parse_content()
        if self.content and not self.tags:
            self._extract_tags()
    
    def _parse_content(self) -> None:
        """解析内容为块"""
        lines = self.content.split('\n')
        current_block = []
        
        for line in lines:
            # 检测块边界
            if line.strip() == '' and current_block:
                self._add_block('\n'.join(current_block))
                current_block = []
            else:
                current_block.append(line)
        
        # 处理最后一块
        if current_block:
            self._add_block('\n'.join(current_block))
    
    def _add_block(self, content: str) -> None:
        """添加块"""
        content = content.strip()
        if not content:
            return
        
        block_type = "paragraph"
        level = 0
        
        # 检测标题
        if content.startswith('# '):
            block_type = "heading"
            level = 1
        elif content.startswith('## '):
            block_type = "heading"
            level = 2
        elif content.startswith('### '):
            block_type = "heading"
            level = 3
        elif content.startswith('- ') or content.startswith('* '):
            block_type = "list"
        elif content.startswith('```'):
            block_type = "code"
        elif content.startswith('>'):
            block_type = "quote"
        
        block = NoteBlock(
            content=content,
            block_type=block_type,
            level=level
        )
        
        self.blocks.append(block)
    
    def _extract_tags(self) -> None:
        """从内容中提取标签"""
        # #tag 格式
        tag_pattern = r'#([a-zA-Z0-9_\-\u4e00-\u9fa5]+)'
        tags = re.findall(tag_pattern, self.content)
        self.tags.update(tags)
    
    def extract_wikilinks(self) -> List[str]:
        """
        提取Wiki风格链接 [[Note Title]]
        """
        pattern = r'\[\[([^\]]+)\]\]'
        matches = re.findall(pattern, self.content)
        return matches
    
    def extract_embeds(self) -> List[str]:
        """
        提取嵌入引用 ![[]]
        """
        pattern = r'!\[\[([^\]]+)\]\]'
        matches = re.findall(pattern, self.content)
        return matches
    
    def extract_block_refs(self) -> List[str]:
        """
        提取块引用 ^block-id
        """
        pattern = r'\^([a-zA-Z0-9_-]+)'
        matches = re.findall(pattern, self.content)
        return matches
    
    def get_outgoing_links(self) -> List[str]:
        """获取出链目标"""
        return self.extract_wikilinks()
    
    def update_content(self, new_content: str) -> None:
        """更新内容"""
        self.content = new_content
        self.updated_at = datetime.utcnow()
        
        # 重新解析
        self.blocks = []
        self._parse_content()
        self.tags = set()
        self._extract_tags()
    
    def add_tag(self, tag: str) -> None:
        """添加标签"""
        self.tags.add(tag)
        self.updated_at = datetime.utcnow()
    
    def remove_tag(self, tag: str) -> None:
        """移除标签"""
        self.tags.discard(tag)
        self.updated_at = datetime.utcnow()
    
    def set_property(self, key: str, value: Any) -> None:
        """设置属性"""
        self.properties[key] = value
        self.updated_at = datetime.utcnow()
    
    def get_property(self, key: str, default: Any = None) -> Any:
        """获取属性"""
        return self.properties.get(key, default)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "workspace_id": self.workspace_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tags": list(self.tags),
            "properties": self.properties,
            "note_type": self.note_type,
            "status": self.status,
            "outgoing_links_count": len(self.outgoing_links),
            "incoming_links_count": len(self.incoming_links),
            "children_count": len(self.children_ids)
        }
    
    def to_markdown(self) -> str:
        """导出为Markdown"""
        lines = []
        
        # Frontmatter
        if self.properties:
            lines.append("---")
            for key, value in self.properties.items():
                lines.append(f"{key}: {value}")
            lines.append("---")
            lines.append("")
        
        # 标题
        lines.append(f"# {self.title}")
        lines.append("")
        
        # 内容
        lines.append(self.content)
        
        # 标签
        if self.tags:
            lines.append("")
            lines.append("Tags: " + " ".join(f"#{tag}" for tag in self.tags))
        
        return '\n'.join(lines)


@dataclass
class NoteRelation:
    """
    笔记关系（用于图谱）
    """
    source_id: str
    target_id: str
    relation_type: str  # links_to, references, similar, parent_of, child_of
    strength: float = 1.0  # 关系强度 0-1
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphNode:
    """图谱节点"""
    id: str
    label: str
    node_type: str  # note, tag, concept
    x: float = 0.0
    y: float = 0.0
    size: float = 1.0  # 基于连接数
    color: str = "#4A90D9"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """图谱边"""
    id: str
    source: str
    target: str
    edge_type: str
    weight: float = 1.0
    label: Optional[str] = None
