"""
Knowledge Extractor - 知识提取器

AI驱动的知识发现，从对话中识别值得保存的知识点
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)


class KnowledgeType(Enum):
    """知识类型"""
    FACT = "fact"  # 事实性知识
    CONCEPT = "concept"  # 概念定义
    INSIGHT = "insight"  # 洞察/见解
    DECISION = "decision"  # 决策记录
    PROCEDURE = "procedure"  # 流程/步骤
    PREFERENCE = "preference"  # 用户偏好


@dataclass
class KnowledgeItem:
    """提取的知识项"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    title: str = ""
    knowledge_type: KnowledgeType = KnowledgeType.FACT
    
    # 来源信息
    source_query: str = ""
    source_response: str = ""
    
    # 上下文
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    workspace_id: Optional[str] = None
    
    # 元数据
    confidence: float = 0.8
    importance: int = 2  # 1-5
    tags: List[str] = field(default_factory=list)
    
    # 相关实体
    entities: List[str] = field(default_factory=list)
    
    # 建议链接
    suggested_links: List[str] = field(default_factory=list)
    
    # 时间
    extracted_at: str = field(default_factory=lambda: str(uuid.uuid4()))


class KnowledgeExtractor:
    """知识提取器"""
    
    def __init__(self):
        self._llm = None
    
    def _get_llm(self):
        if self._llm is None:
            from model.model_gateway.gateway import get_model_gateway
            self._llm = get_model_gateway()
        return self._llm
    
    async def should_extract(
        self,
        query: str,
        response: str,
        tool_calls: Optional[List[Dict]] = None
    ) -> bool:
        """
        判断对话是否包含值得提取的知识
        """
        # 启发式规则
        
        # 1. 长度检查
        if len(response) < 100:
            return False
        
        # 2. 关键词检查
        knowledge_keywords = [
            "定义", "概念", "原理", "方法", "步骤",
            "结论是", "建议", "发现", "总结",
            "important", "key", "conclusion", "recommend",
        ]
        if any(kw in response for kw in knowledge_keywords):
            return True
        
        # 3. 工具调用检查（有工具调用的对话通常有价值）
        if tool_calls and len(tool_calls) > 0:
            return True
        
        # 4. LLM判断（用于复杂情况）
        if len(response) > 500:
            return await self._llm_judge_worthiness(query, response)
        
        return False
    
    async def _llm_judge_worthiness(self, query: str, response: str) -> bool:
        """使用LLM判断是否值得提取"""
        try:
            llm = self._get_llm()
            
            prompt = f"""判断以下对话是否包含值得长期保存的知识。

用户问题: {query[:200]}
AI回答: {response[:1000]}

值得保存的知识通常包括:
- 事实性信息 (人名、地名、数据等)
- 概念定义和解释
- 有价值的见解或洞察
- 决策或结论
- 有用的方法或流程

是否值得保存? 只回答 "是" 或 "否"。"""
            
            result = await llm.complete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10
            )
            
            return "是" in result.content or "yes" in result.content.lower()
        except Exception as e:
            logger.warning(f"LLM judgment failed: {e}")
            return False
    
    async def extract(
        self,
        query: str,
        response: str,
        reasoning_steps: Optional[List[Dict]] = None,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None
    ) -> Optional[KnowledgeItem]:
        """
        从对话中提取知识
        """
        try:
            llm = self._get_llm()
            
            prompt = f"""从以下对话中提取关键知识点。

用户问题: {query}

AI回答: {response}

请提取:
1. 标题 (简洁, 20字以内)
2. 内容 (核心知识, 100字以内)
3. 类型 (fact/concept/insight/decision/procedure/preference)
4. 关键词 (3-5个)

以JSON格式返回:
{{
  "title": "...",
  "content": "...",
  "type": "...",
  "keywords": ["..."],
  "confidence": 0.9
}}"""
            
            result = await llm.complete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300
            )
            
            # 解析JSON结果
            import json
            import re
            
            # 提取JSON
            json_match = re.search(r'\{[\s\S]*\}', result.content)
            if json_match:
                data = json.loads(json_match.group())
                
                knowledge = KnowledgeItem(
                    title=data.get("title", "提取的知识"),
                    content=data.get("content", response[:200]),
                    knowledge_type=KnowledgeType(data.get("type", "fact")),
                    source_query=query,
                    source_response=response,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    confidence=data.get("confidence", 0.8),
                    tags=data.get("keywords", [])
                )
                
                logger.info(f"Knowledge extracted: {knowledge.title}")
                return knowledge
        
        except Exception as e:
            logger.warning(f"Knowledge extraction failed: {e}")
        
        return None
    
    async def suggest_related_knowledge(
        self,
        knowledge: KnowledgeItem,
        existing_notes: List[Dict]
    ) -> List[str]:
        """建议相关的现有知识"""
        # 基于标签和内容的相似度推荐
        suggestions = []
        
        for note in existing_notes:
            # 标签匹配
            note_tags = set(note.get("tags", []))
            knowledge_tags = set(knowledge.tags)
            
            if note_tags & knowledge_tags:  # 有交集
                suggestions.append(note.get("id"))
        
        return suggestions[:3]  # 最多3个建议
