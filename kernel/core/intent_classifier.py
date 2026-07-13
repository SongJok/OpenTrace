"""
意图分类器 - 第一层处理

参考 ChatGPT 的多层意图识别机制：
1. 直接响应型 (Direct) - 问候、确认等
2. 知识查询型 (Knowledge) - RAG 检索
3. 工具调用型 (Tool) - 需要外部工具
4. 复杂推理型 (Reasoning) - 多步推理
5. 澄清确认型 (Clarification) - 需要用户澄清
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Dict, Any, List
import json
import re

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


class IntentType(Enum):
    """意图类型"""
    DIRECT = auto()          # 直接回答（问候、简单问题）
    KNOWLEDGE = auto()       # 知识查询（RAG）
    TOOL = auto()            # 工具调用
    REASONING = auto()       # 复杂推理（o1-like）
    CLARIFICATION = auto()   # 需要澄清
    MEMORY = auto()          # 记忆操作
    CONVERSATION = auto()    # 对话控制（分支、编辑等）


@dataclass
class IntentClassification:
    """意图分类结果"""
    intent_type: IntentType
    confidence: float
    query_complexity: str  # "simple", "medium", "complex"
    expected_tokens: int
    requires_memory: bool
    requires_tools: List[str]
    reasoning_depth: int  # 1-5，参考 o1 的推理深度
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_type": self.intent_type.name,
            "confidence": self.confidence,
            "query_complexity": self.query_complexity,
            "expected_tokens": self.expected_tokens,
            "requires_memory": self.requires_memory,
            "requires_tools": self.requires_tools,
            "reasoning_depth": self.reasoning_depth,
            "metadata": self.metadata
        }


class IntentClassifier:
    """
    意图分类器
    
    实现类似 ChatGPT 的多层意图识别：
    - L1: 快速启发式分类
    - L2: 深度分析模型
    """
    
    # 简单查询关键词
    SIMPLE_KEYWORDS = [
        "你好", "您好", "hi", "hello", "hey",
        "谢谢", "再见", "拜拜", "好的", "ok"
    ]
    
    # 工具调用关键词
    TOOL_KEYWORDS = {
        "weather": ["天气", "温度", "下雨", "weather", "temperature"],
        "time": ["时间", "几点", "日期", "time", "date"],
        "database": ["查询", "数据", "数据库", "sql", "query"],
        "search": ["搜索", "查找", "search", "find", "lookup"]
    }
    
    # 复杂推理关键词
    REASONING_KEYWORDS = [
        "分析", "推理", "计算", "规划", "比较", "对比",
        "为什么", "原因", "影响", "评估", "预测", "优化",
        "analyze", "reason", "calculate", "plan", "compare",
        "why", "cause", "impact", "evaluate", "predict", "optimize"
    ]
    
    def __init__(self):
        self._gateway = None
    
    def _get_gateway(self):
        if self._gateway is None:
            from model.model_gateway.gateway import get_model_gateway
            self._gateway = get_model_gateway()
        return self._gateway
    
    async def classify(
        self,
        query: str,
        context: Optional[Dict] = None
    ) -> IntentClassification:
        """
        分层意图分类
        
        L1: 快速启发式分类（本地规则）
        L2: LLM 深度分类（复杂场景）
        """
        with tracer.start_as_current_span("intent.classify") as span:
            span.set_attribute("query", query[:100])
            
            # L1: 快速分类
            heuristic_result = self._heuristic_classify(query)
            
            # 如果置信度足够高，直接返回
            if heuristic_result.confidence >= 0.9:
                logger.debug(f"Heuristic classification: {heuristic_result.intent_type.name}")
                span.set_attribute("method", "heuristic")
                span.set_attribute("intent", heuristic_result.intent_type.name)
                return heuristic_result
            
            # L2: LLM 深度分类
            llm_result = await self._llm_classify(query, context)
            
            # 合并结果
            final_result = self._merge_results(heuristic_result, llm_result)
            
            span.set_attribute("method", "llm_enhanced")
            span.set_attribute("intent", final_result.intent_type.name)
            span.set_attribute("confidence", final_result.confidence)
            
            return final_result
    
    def _heuristic_classify(self, query: str) -> IntentClassification:
        """启发式快速分类"""
        query_lower = query.lower().strip()
        
        # 1. 检查是否为简单问候/确认
        if any(kw in query_lower for kw in self.SIMPLE_KEYWORDS):
            return IntentClassification(
                intent_type=IntentType.DIRECT,
                confidence=0.95,
                query_complexity="simple",
                expected_tokens=100,
                requires_memory=False,
                requires_tools=[],
                reasoning_depth=1,
                metadata={"method": "heuristic_greeting"}
            )
        
        # 2. 检查是否需要工具
        required_tools = []
        for tool_name, keywords in self.TOOL_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                required_tools.append(tool_name)
        
        if required_tools:
            return IntentClassification(
                intent_type=IntentType.TOOL,
                confidence=0.85,
                query_complexity="medium",
                expected_tokens=300,
                requires_memory=True,
                requires_tools=required_tools,
                reasoning_depth=2,
                metadata={"method": "heuristic_tools", "matched_tools": required_tools}
            )
        
        # 3. 检查是否需要复杂推理
        reasoning_count = sum(1 for kw in self.REASONING_KEYWORDS if kw in query_lower)
        if reasoning_count >= 2 or len(query) > 200:
            return IntentClassification(
                intent_type=IntentType.REASONING,
                confidence=0.75,
                query_complexity="complex",
                expected_tokens=800,
                requires_memory=True,
                requires_tools=[],
                reasoning_depth=4,
                metadata={"method": "heuristic_reasoning", "keyword_count": reasoning_count}
            )
        
        # 4. 默认知识查询
        return IntentClassification(
            intent_type=IntentType.KNOWLEDGE,
            confidence=0.7,
            query_complexity="medium",
            expected_tokens=500,
            requires_memory=True,
            requires_tools=[],
            reasoning_depth=2,
            metadata={"method": "heuristic_default"}
        )
    
    async def _llm_classify(
        self,
        query: str,
        context: Optional[Dict]
    ) -> IntentClassification:
        """LLM 深度分类"""
        try:
            gateway = self._get_gateway()
            
            messages = [
                {
                    "role": "system",
                    "content": """你是一个意图分类专家。分析用户查询并输出JSON格式结果。

意图类型定义：
- DIRECT: 简单问候、确认、礼貌用语（如"你好""谢谢"）
- KNOWLEDGE: 知识查询、信息检索（如"什么是Python"）
- TOOL: 需要调用工具获取实时信息（如"现在几点""天气如何"）
- REASONING: 需要深度推理、分析、计算（如"分析优缺点""预测趋势"）
- CLARIFICATION: 表述不清，需要用户澄清
- MEMORY: 与记忆管理相关（如"记住这个""我之前说过"）
- CONVERSATION: 对话控制（如"重新开始""回到之前"）

输出格式：
{
    "intent": "DIRECT|KNOWLEDGE|TOOL|REASONING|CLARIFICATION|MEMORY|CONVERSATION",
    "confidence": 0.0-1.0,
    "complexity": "simple|medium|complex",
    "expected_tokens": 数字,
    "requires_tools": ["工具名"],
    "reasoning_depth": 1-5,
    "clarification_needed": false,
    "reason": "分类理由"
}"""
                },
                {
                    "role": "user",
                    "content": f"请分析以下查询的意图：\n\n{query}"
                }
            ]
            
            from model.model_gateway.gateway import LLMRole
            response = await gateway.complete(
                messages=messages,
                role=LLMRole.ROUTER,
                temperature=0.0,
                max_tokens=512
            )
            
            # 解析 JSON
            content = response.content.strip()
            # 提取 JSON 部分
            json_match = re.search(r'\{[^}]+\}', content, re.DOTALL)
            if json_match:
                content = json_match.group()
            
            result = json.loads(content)
            
            intent_map = {
                "DIRECT": IntentType.DIRECT,
                "KNOWLEDGE": IntentType.KNOWLEDGE,
                "TOOL": IntentType.TOOL,
                "REASONING": IntentType.REASONING,
                "CLARIFICATION": IntentType.CLARIFICATION,
                "MEMORY": IntentType.MEMORY,
                "CONVERSATION": IntentType.CONVERSATION
            }
            
            return IntentClassification(
                intent_type=intent_map.get(result.get("intent"), IntentType.KNOWLEDGE),
                confidence=float(result.get("confidence", 0.7)),
                query_complexity=result.get("complexity", "medium"),
                expected_tokens=int(result.get("expected_tokens", 500)),
                requires_memory=True,
                requires_tools=result.get("requires_tools", []),
                reasoning_depth=int(result.get("reasoning_depth", 2)),
                metadata={
                    "method": "llm",
                    "reason": result.get("reason", ""),
                    "raw": result
                }
            )
            
        except Exception as e:
            logger.warning(f"LLM classification failed: {e}")
            # 降级到知识查询
            return IntentClassification(
                intent_type=IntentType.KNOWLEDGE,
                confidence=0.6,
                query_complexity="medium",
                expected_tokens=500,
                requires_memory=True,
                requires_tools=[],
                reasoning_depth=2,
                metadata={"method": "llm_fallback", "error": str(e)}
            )
    
    def _merge_results(
        self,
        heuristic: IntentClassification,
        llm: IntentClassification
    ) -> IntentClassification:
        """合并启发式和LLM结果"""
        # 如果两者意图一致，提高置信度
        if heuristic.intent_type == llm.intent_type:
            confidence = min(heuristic.confidence * 0.3 + llm.confidence * 0.7 + 0.1, 1.0)
            return IntentClassification(
                intent_type=heuristic.intent_type,
                confidence=confidence,
                query_complexity=llm.query_complexity,
                expected_tokens=max(heuristic.expected_tokens, llm.expected_tokens),
                requires_memory=heuristic.requires_memory or llm.requires_memory,
                requires_tools=list(set(heuristic.requires_tools + llm.requires_tools)),
                reasoning_depth=max(heuristic.reasoning_depth, llm.reasoning_depth),
                metadata={
                    "method": "merged",
                    "heuristic": heuristic.metadata,
                    "llm": llm.metadata
                }
            )
        
        # 意图不一致时，取置信度高的
        if heuristic.confidence > llm.confidence:
            return heuristic
        return llm
