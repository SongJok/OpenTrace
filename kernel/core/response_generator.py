"""
Response Generator - Response Generator

Coordinate responses from different model roles:
- FAST: Fast simple answers
- KNOWLEDGE: Knowledge queries  
- REASONING: Complex reasoning (o1-like)
"""

from dataclasses import dataclass
from typing import AsyncIterator, List, Dict, Any, Optional
from datetime import datetime

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


@dataclass
class GenerationResult:
    """Generation result"""
    content: str
    reasoning_steps: List[Dict]
    tool_calls: List[Dict]
    citations: List[Dict]
    tokens_used: Dict[str, int]
    model_used: str
    latency_ms: int


class ResponseGenerator:
    """
    Response generator
    
    Select the best generation strategy based on intent type
    """
    
    def __init__(self):
        self._gateway = None
    
    def _get_gateway(self):
        if self._gateway is None:
            from model.model_gateway.gateway import get_model_gateway
            self._gateway = get_model_gateway()
        return self._gateway
    
    async def generate(self, query: str, intent, context, stream: bool = False) -> GenerationResult:
        """Generate response"""
        with tracer.start_as_current_span("response.generate") as span:
            span.set_attribute("query", query[:50])
            
            role = self._select_role(intent)
            messages = context.to_llm_messages()
            messages.append({"role": "user", "content": query})
            
            t0 = datetime.utcnow()
            
            if stream:
                content = ""
            else:
                response = await self._get_gateway().complete(messages=messages, role=role)
                content = response.content
            
            latency = int((datetime.utcnow() - t0).total_seconds() * 1000)
            
            return GenerationResult(
                content=content,
                reasoning_steps=[],
                tool_calls=[],
                citations=[],
                tokens_used={"prompt": 0, "completion": 0},
                model_used=str(role),
                latency_ms=latency
            )
    
    async def stream_generate(self, query: str, intent, context, plan=None) -> AsyncIterator[str]:
        """Stream generate response"""
        role = self._select_role(intent)
        messages = context.to_llm_messages()
        messages.append({"role": "user", "content": query})
        
        async for chunk in self._get_gateway().stream(messages=messages, role=role):
            yield chunk
    
    def _select_role(self, intent):
        """Select model role based on intent"""
        from .intent_classifier import IntentType
        from model.model_gateway.gateway import LLMRole
        
        intent_type = getattr(intent, 'intent_type', None)
        if intent_type is None:
            return LLMRole.QUERY
        
        mapping = {
            IntentType.DIRECT: LLMRole.FAST,
            IntentType.KNOWLEDGE: LLMRole.KNOWLEDGE,
            IntentType.TOOL: LLMRole.QUERY,
            IntentType.REASONING: LLMRole.QUERY,
            IntentType.CLARIFICATION: LLMRole.FAST,
            IntentType.MEMORY: LLMRole.KNOWLEDGE,
            IntentType.CONVERSATION: LLMRole.FAST
        }
        
        return mapping.get(intent_type, LLMRole.QUERY)


class ReasoningGenerator:
    """Deep reasoning generator (o1-like)"""
    
    def __init__(self):
        self._gateway = None
    
    def _get_gateway(self):
        if self._gateway is None:
            from model.model_gateway.gateway import get_model_gateway
            self._gateway = get_model_gateway()
        return self._gateway
    
    async def generate_with_reasoning(self, query: str, context, depth: int = 3) -> GenerationResult:
        """Generate response with reasoning chain"""
        reasoning_steps = [{"step": "decomposition", "query": query}]
        
        messages = [
            {"role": "system", "content": "Think step by step and provide detailed reasoning."},
            {"role": "user", "content": query}
        ]
        
        from model.model_gateway.gateway import LLMRole
        response = await self._get_gateway().complete(messages=messages, role=LLMRole.QUERY)
        
        reasoning_steps.append({"step": "reasoning_complete"})
        
        return GenerationResult(
            content=response.content,
            reasoning_steps=reasoning_steps,
            tool_calls=[],
            citations=[],
            tokens_used={"prompt": 0, "completion": 0},
            model_used="reasoning",
            latency_ms=0
        )
