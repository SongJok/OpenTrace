"""
Turn Processor - 对话轮次处理器

参考 ChatGPT 的 turn processing pipeline：
1. Pre-processing (预处理)
2. Intent Classification (意图分类)  
3. Context Building (上下文构建)
4. Planning (规划)
5. Execution (执行)
6. Post-processing (后处理)
7. Memory Update (记忆更新)
"""

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator, Optional, Dict, Any, List
from datetime import datetime, timezone

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

from .intent_classifier import IntentClassifier, IntentType
from .context_manager import ContextManager
from .response_generator import ResponseGenerator, ReasoningGenerator
from .streaming_engine import StreamingEngine, StreamEvent
from reasoning.visualizer import ReasoningVisualizer, StepType, StepStatus

logger = get_logger(__name__)
tracer = get_tracer(__name__)


@dataclass
class TurnRequest:
    """对话请求"""
    query: str
    session_id: str
    user_id: str
    conversation_id: str
    workspace_id: Optional[str] = None
    stream: bool = True
    enable_reasoning: bool = True
    metadata: Optional[Dict] = None


@dataclass
class TurnResponse:
    """对话响应"""
    content: str
    session_id: str
    conversation_id: str
    reasoning_steps: List[Dict]
    tool_calls: List[Dict]
    citations: List[Dict]
    latency_ms: int
    tokens_used: Dict[str, int]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "reasoning_steps": self.reasoning_steps,
            "tool_calls": self.tool_calls,
            "citations": self.citations,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used
        }


class TurnProcessor:
    """
    对话轮次处理器
    
    实现完整的处理流水线，参考 ChatGPT 的 turn processing
    """
    
    def __init__(self):
        self.intent_classifier = IntentClassifier()
        self.context_manager = ContextManager()
        self.response_generator = ResponseGenerator()
        self.reasoning_generator = ReasoningGenerator()
        self.streaming_engine = StreamingEngine()
        self._active_turns: Dict[str, datetime] = {}
    
    async def process(self, request: TurnRequest) -> TurnResponse:
        """
        同步处理单轮对话
        """
        with tracer.start_as_current_span("turn.process") as span:
            span.set_attribute("session_id", request.session_id)
            span.set_attribute("query", request.query[:50])
            
            t0 = datetime.now(timezone.utc)
            
            # 1. 意图分类
            intent = await self.intent_classifier.classify(
                request.query,
                {"session_id": request.session_id, "user_id": request.user_id}
            )
            span.set_attribute("intent", intent.intent_type.name)
            
            # 2. 构建上下文
            context = await self.context_manager.build_context(
                session_id=request.session_id,
                user_id=request.user_id,
                current_query=request.query
            )
            
            # 3. 生成响应
            if intent.intent_type == IntentType.REASONING and request.enable_reasoning:
                # 使用深度推理
                result = await self.reasoning_generator.generate_with_reasoning(
                    query=request.query,
                    context=context,
                    depth=intent.reasoning_depth
                )
            else:
                result = await self.response_generator.generate(
                    query=request.query,
                    intent=intent,
                    context=context,
                    stream=False
                )
            
            # 4. 更新记忆
            await self._update_memory(request, result)
            
            latency = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            
            return TurnResponse(
                content=result.content,
                session_id=request.session_id,
                conversation_id=request.conversation_id,
                reasoning_steps=[intent.to_dict()] + result.reasoning_steps,
                tool_calls=result.tool_calls,
                citations=result.citations,
                latency_ms=latency,
                tokens_used=result.tokens_used
            )
    
    async def stream(self, request: TurnRequest) -> AsyncIterator[str]:
        """
        流式处理对话
        
        输出 SSE 格式的流事件
        """
        with tracer.start_as_current_span("turn.stream") as span:
            span.set_attribute("session_id", request.session_id)
            span.set_attribute("query", request.query[:50])
            
            t0 = datetime.now(timezone.utc)
            
            # 创建推理可视化器
            visualizer = ReasoningVisualizer(request.session_id)
            
            # ========== Step 1: 分析 ==========
            step1 = visualizer.create_step(
                StepType.ANALYSIS,
                "正在理解您的请求...",
                "分析查询意图和复杂度"
            )
            visualizer.start_step(step1.id)
            
            intent = await self.intent_classifier.classify(
                request.query,
                {"session_id": request.session_id, "user_id": request.user_id}
            )
            
            visualizer.update_step_progress(step1.id, 1.0)
            visualizer.complete_step(step1.id)
            
            # 发送步骤更新
            yield self._format_sse("reasoning", visualizer.to_stream_event())
            
            # ========== Step 2: 检索记忆 ==========
            step2 = visualizer.create_step(
                StepType.RETRIEVING,
                "正在检索相关记忆...",
                "从历史对话和知识库中查找相关信息"
            )
            visualizer.start_step(step2.id)
            
            context = await self.context_manager.build_context(
                session_id=request.session_id,
                user_id=request.user_id,
                current_query=request.query
            )
            
            visualizer.update_step_progress(step2.id, 1.0)
            visualizer.complete_step(step2.id)
            yield self._format_sse("reasoning", visualizer.to_stream_event())
            
            # ========== Step 3: 规划 ==========
            step3 = visualizer.create_step(
                StepType.PLANNING,
                "正在规划响应...",
                f"查询类型: {intent.intent_type.name}, 复杂度: {intent.query_complexity}"
            )
            visualizer.start_step(step3.id)
            
            # 规划是否需要工具等
            plan = self._create_plan(intent, context)
            
            # 模拟规划思考时间
            await asyncio.sleep(0.2)
            
            visualizer.complete_step(step3.id)
            yield self._format_sse("reasoning", visualizer.to_stream_event())
            
            # ========== Step 4: 执行与生成 ==========
            step4 = visualizer.create_step(
                StepType.SYNTHESIZING,
                "正在生成回答...",
                "整合信息并生成最终回复"
            )
            visualizer.start_step(step4.id)
            
            # 流式生成内容
            content_buffer = []
            
            async for chunk in self.response_generator.stream_generate(
                query=request.query,
                intent=intent,
                context=context,
                plan=plan
            ):
                content_buffer.append(chunk)
                yield self._format_sse("content", {"text": chunk})
            
            full_content = "".join(content_buffer)
            visualizer.complete_step(step4.id)
            yield self._format_sse("reasoning", visualizer.to_stream_event())
            
            # ========== Step 5: 完成 ==========
            step5 = visualizer.create_step(
                StepType.COMPLETE,
                "处理完成",
                "响应已生成"
            )
            visualizer.start_step(step5.id)
            visualizer.complete_step(step5.id)
            
            yield self._format_sse("reasoning", visualizer.to_stream_event())
            
            # 发送完成事件
            latency = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            yield self._format_sse("done", {
                "latency_ms": latency,
                "complete": True
            })
            
            # 后台更新记忆（不阻塞响应）
            asyncio.create_task(self._update_memory(
                request,
                TurnResponse(
                    content=full_content,
                    session_id=request.session_id,
                    conversation_id=request.conversation_id,
                    reasoning_steps=[s.to_dict() for s in visualizer.steps],
                    tool_calls=[],
                    citations=[],
                    latency_ms=latency,
                    tokens_used={}
                )
            ))
    
    def _format_sse(self, event_type: str, data: Dict) -> str:
        """格式化 SSE 事件"""
        import json
        return f"data: {json.dumps({'type': event_type, 'data': data})}\n\n"
    
    def _create_plan(self, intent, context) -> Dict:
        """创建执行计划"""
        return {
            "intent": intent.intent_type.name if hasattr(intent, 'intent_type') else "unknown",
            "confidence": getattr(intent, 'confidence', 0.7),
            "requires_tools": getattr(intent, 'requires_tools', []),
            "reasoning_depth": getattr(intent, 'reasoning_depth', 2),
            "context_window_tokens": getattr(context, 'token_count', 0),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    async def _update_memory(self, request: TurnRequest, response: TurnResponse):
        """更新记忆"""
        try:
            from memory.unified.manager import UnifiedMemoryManager
            
            memory = UnifiedMemoryManager()
            
            await memory.save_turn(
                session_id=request.session_id,
                user_id=request.user_id,
                query=request.query,
                response=response.content,
                tool_calls=response.tool_calls,
                metadata={
                    "intent": response.reasoning_steps[0] if response.reasoning_steps else None,
                    "latency_ms": response.latency_ms,
                    "conversation_id": request.conversation_id
                }
            )
            
            logger.debug(f"Memory updated for session {request.session_id}")
            
        except Exception as e:
            logger.warning(f"Failed to update memory: {e}")


class TurnPipeline:
    """
    高级流水线处理器
    
    支持更复杂的处理流程，如多轮规划、工具编排等
    """
    
    def __init__(self):
        self.processor = TurnProcessor()
        self.middlewares: List[Any] = []
    
    def add_middleware(self, middleware):
        """添加中间件"""
        self.middlewares.append(middleware)
    
    async def execute(self, request: TurnRequest) -> TurnResponse:
        """执行带中间件的流水线"""
        # 前置处理
        for mw in self.middlewares:
            if hasattr(mw, 'before_process'):
                request = await mw.before_process(request) or request
        
        # 主处理
        response = await self.processor.process(request)
        
        # 后置处理
        for mw in reversed(self.middlewares):
            if hasattr(mw, 'after_process'):
                response = await mw.after_process(response) or response
        
        return response
