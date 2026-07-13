"""
Progressive Summarizer - 渐进式摘要系统

参考LLMwiki的思想，实现多级摘要：
- L1: 原始内容
- L2: 段落摘要
- L3: 页面摘要
- L4: 知识卡片
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)


class SummaryLevel(Enum):
    """摘要级别"""
    L1_RAW = "l1_raw"  # 原始内容
    L2_PARAGRAPH = "l2_paragraph"  # 段落摘要
    L3_DOCUMENT = "l3_document"  # 文档摘要
    L4_CARD = "l4_card"  # 知识卡片


@dataclass
class ParagraphSummary:
    """段落摘要"""
    paragraph_id: str
    original_text: str
    key_points: List[str]
    importance_score: float = 0.5


@dataclass
class DocumentSummary:
    """文档摘要"""
    content: str
    key_topics: List[str]
    key_entities: List[str]
    main_arguments: List[str]
    word_count: int = 0


@dataclass
class KnowledgeCard:
    """知识卡片"""
    title: str
    key_points: List[str]
    tags: List[str]
    connections: List[str]
    source: str


@dataclass
class ProgressiveSummary:
    """完整的多级摘要"""
    note_id: str
    l1_raw: str
    l2_paragraph: List[ParagraphSummary] = field(default_factory=list)
    l3_document: Optional[DocumentSummary] = None
    l4_card: Optional[KnowledgeCard] = None
    
    def get_for_complexity(self, complexity: str) -> str:
        """根据查询复杂度返回合适的摘要级别"""
        if complexity == "simple" and self.l4_card:
            return self.format_card()
        elif complexity == "medium" and self.l3_document:
            return self.format_document()
        elif complexity == "detailed" and self.l2_paragraph:
            return self.format_paragraph()
        return self.l1_raw
    
    def format_card(self) -> str:
        """格式化知识卡片"""
        if not self.l4_card:
            return ""
        lines = [f"# {self.l4_card.title}", ""]
        for point in self.l4_card.key_points:
            lines.append(f"• {point}")
        if self.l4_card.connections:
            lines.extend(["", "相关: " + ", ".join(self.l4_card.connections)])
        return "\n".join(lines)
    
    def format_document(self) -> str:
        """格式化文档摘要"""
        if not self.l3_document:
            return ""
        lines = [self.l3_document.content, ""]
        if self.l3_document.main_arguments:
            lines.extend(["核心论点:", *[f"• {arg}" for arg in self.l3_document.main_arguments]])
        return "\n".join(lines)
    
    def format_paragraph(self) -> str:
        """格式化段落摘要"""
        lines = []
        for para in self.l2_paragraph[:5]:  # 限制数量
            for point in para.key_points[:2]:  # 每个段落最多2个要点
                lines.append(f"• {point}")
        return "\n".join(lines)


class ProgressiveSummarizer:
    """渐进式摘要器"""
    
    def __init__(self):
        self._llm = None
    
    def _get_llm(self):
        if self._llm is None:
            from model.model_gateway.gateway import get_model_gateway
            self._llm = get_model_gateway()
        return self._llm
    
    async def summarize(
        self,
        note_id: str,
        content: str,
        title: str = ""
    ) -> ProgressiveSummary:
        """
        生成完整的多级摘要
        """
        summary = ProgressiveSummary(
            note_id=note_id,
            l1_raw=content
        )
        
        # L2: 段落摘要
        summary.l2_paragraph = await self._summarize_paragraphs(content)
        
        # L3: 文档摘要
        summary.l3_document = await self._summarize_document(content, title)
        
        # L4: 知识卡片
        summary.l4_card = await self._create_knowledge_card(
            content, title, summary.l3_document
        )
        
        return summary
    
    async def _summarize_paragraphs(self, content: str) -> List[ParagraphSummary]:
        """生成段落摘要（L2）"""
        # 分段
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', content) if p.strip()]
        
        summaries = []
        for i, para in enumerate(paragraphs[:20]):  # 限制段落数
            # 使用启发式提取关键句
            key_points = self._extract_key_sentences(para)
            
            # 计算重要性
            importance = self._calculate_importance(para)
            
            summaries.append(ParagraphSummary(
                paragraph_id=f"p{i}",
                original_text=para[:200],
                key_points=key_points,
                importance_score=importance
            ))
        
        # 按重要性排序
        summaries.sort(key=lambda x: x.importance_score, reverse=True)
        return summaries
    
    async def _summarize_document(
        self,
        content: str,
        title: str
    ) -> DocumentSummary:
        """生成文档摘要（L3）"""
        # 提取关键实体
        entities = self._extract_entities(content)
        
        # 提取主题
        topics = self._extract_topics(content)
        
        # 生成一句话摘要
        word_count = len(content)
        if word_count > 200:
            summary = await self._generate_summary_with_llm(content, "一句话总结核心内容")
        else:
            summary = content
        
        return DocumentSummary(
            content=summary,
            key_topics=topics[:5],
            key_entities=entities[:10],
            main_arguments=[],
            word_count=word_count
        )
    
    async def _create_knowledge_card(
        self,
        content: str,
        title: str,
        doc_summary: Optional[DocumentSummary]
    ) -> KnowledgeCard:
        """生成知识卡片（L4）"""
        # 提取最精炼的知识点
        key_points = self._extract_key_points(content, max_points=5)
        
        # 提取标签
        tags = doc_summary.key_topics if doc_summary else []
        
        # 提取连接
        connections = doc_summary.key_entities if doc_summary else []
        
        return KnowledgeCard(
            title=title or "知识卡片",
            key_points=key_points,
            tags=tags[:5],
            connections=connections[:5],
            source="document"
        )
    
    def _extract_key_sentences(self, paragraph: str) -> List[str]:
        """从段落中提取关键句"""
        # 启发式：首句、包含关键信息的句子
        sentences = re.split(r'(?<=[。！？.!?])\s+', paragraph)
        
        key_sentences = []
        
        # 首句通常很重要
        if sentences:
            key_sentences.append(sentences[0][:100])
        
        # 包含关键词的句子
        keywords = ["关键", "核心", "重要", "主要", "结论", "总结"]
        for sent in sentences[1:]:
            if any(kw in sent for kw in keywords) and len(sent) > 10:
                key_sentences.append(sent[:100])
                if len(key_sentences) >= 3:
                    break
        
        return key_sentences
    
    def _calculate_importance(self, paragraph: str) -> float:
        """计算段落重要性"""
        score = 0.0
        
        # 长度因子（适中长度更好）
        length = len(paragraph)
        if 50 < length < 500:
            score += 0.3
        
        # 关键词因子
        keywords = ["定义", "概念", "原理", "方法", "步骤", "结论", "建议"]
        for kw in keywords:
            if kw in paragraph:
                score += 0.1
        
        # 结构因子（标题、列表）
        if paragraph.startswith('#') or paragraph.startswith('-'):
            score += 0.2
        
        return min(score, 1.0)
    
    def _extract_entities(self, content: str) -> List[str]:
        """提取关键实体（简化版）"""
        # 这里应该使用NER模型
        # 目前使用简单启发式
        entities = []
        
        # 提取引号中的内容
        quotes = re.findall(r"[\"']([^\"']+)[\"']", content)
        entities.extend(quotes[:5])
        
        # 提取括号中的内容
        parens = re.findall(r'[（(]([^）)]+)[）)]', content)
        entities.extend(parens[:5])
        
        return list(set(entities))
    
    def _extract_topics(self, content: str) -> List[str]:
        """提取主题"""
        # 提取标签
        tags = re.findall(r'#([a-zA-Z0-9_\-\u4e00-\u9fa5]+)', content)
        
        # 提取标题
        headings = re.findall(r'^#{1,3}\s+(.+)$', content, re.MULTILINE)
        
        return tags + headings[:10]
    
    def _extract_key_points(self, content: str, max_points: int = 5) -> List[str]:
        """提取关键点"""
        points = []
        
        # 提取列表项
        list_items = re.findall(r'^[\s]*[-*]\s+(.+)$', content, re.MULTILINE)
        points.extend(list_items[:max_points])
        
        # 如果不够，从段落中提取
        if len(points) < max_points:
            paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
            for para in paragraphs:
                if len(para) < 100 and para not in points:
                    points.append(para)
                    if len(points) >= max_points:
                        break
        
        return points[:max_points]
    
    async def _generate_summary_with_llm(self, content: str, instruction: str) -> str:
        """使用LLM生成摘要"""
        try:
            llm = self._get_llm()
            
            prompt = f"""请{instruction}:

{content[:2000]}

要求:
- 简洁准确
- 保留关键信息
- 50字以内
"""
            
            response = await llm.complete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100
            )
            
            return response.content.strip()
        except Exception as e:
            logger.warning(f"LLM summarization failed: {e}")
            return content[:100] + "..."


# 全局实例
_summarizer_instance: Optional[ProgressiveSummarizer] = None


def get_summarizer() -> ProgressiveSummarizer:
    """获取摘要器实例"""
    global _summarizer_instance
    if _summarizer_instance is None:
        _summarizer_instance = ProgressiveSummarizer()
    return _summarizer_instance
