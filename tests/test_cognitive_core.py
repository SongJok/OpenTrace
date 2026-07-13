"""
Test Suite for Cognitive Core

Tests for the new cognitive kernel implementation
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from kernel.core.intent_classifier import (
    IntentClassifier,
    IntentType,
    IntentClassification,
)
from kernel.core.context_manager import ContextManager, ContextWindow
from kernel.core.streaming_engine import StreamingEngine, StreamEvent
from kernel.core.response_generator import ResponseGenerator, GenerationResult
from kernel.core.turn_processor import TurnProcessor, TurnRequest, TurnResponse


class TestIntentClassifier:
    """测试意图分类器"""
    
    def test_heuristic_classify_greeting(self):
        """测试启发式分类 - 问候语"""
        classifier = IntentClassifier()
        
        result = classifier._heuristic_classify("你好")
        
        assert result.intent_type == IntentType.DIRECT
        assert result.confidence >= 0.9
        assert result.query_complexity == "simple"
    
    def test_heuristic_classify_tool(self):
        """测试启发式分类 - 工具调用"""
        classifier = IntentClassifier()
        
        result = classifier._heuristic_classify("今天天气怎么样")
        
        assert result.intent_type == IntentType.TOOL
        assert "weather" in result.requires_tools
    
    def test_heuristic_classify_reasoning(self):
        """测试启发式分类 - 复杂推理"""
        classifier = IntentClassifier()
        
        result = classifier._heuristic_classify("分析为什么这个问题很复杂")
        
        assert result.intent_type == IntentType.REASONING
        assert result.reasoning_depth >= 3
    
    @pytest.mark.asyncio
    async def test_classify_uses_heuristic_for_high_confidence(self):
        """测试高置信度时使用启发式结果"""
        classifier = IntentClassifier()
        
        # 简单的问候应该直接返回启发式结果
        result = await classifier.classify("你好")
        
        assert result.intent_type == IntentType.DIRECT
        assert result.confidence >= 0.9


class TestContextManager:
    """测试上下文管理器"""
    
    def test_estimate_tokens_simple(self):
        """测试简单的 token 估算"""
        manager = ContextManager()
        
        messages = [
            {"role": "user", "content": "Hello world"},
            {"role": "assistant", "content": "Hi there!"}
        ]
        system = "You are an AI."
        
        tokens = manager._estimate_tokens(messages, system)
        
        assert tokens > 0
        assert isinstance(tokens, int)
    
    def test_build_system_prompt(self):
        """测试系统提示词构建"""
        manager = ContextManager()
        
        # 模拟 memory_context
        class MockContext:
            relevant_memories = []
        
        prompt = manager._build_system_prompt(MockContext(), "查询 Python 代码")
        
        assert "OpenTrace" in prompt
    
    def test_process_history_empty(self):
        """测试空历史处理"""
        manager = ContextManager()
        
        class MockContext:
            recent_turns = []
        
        messages = manager._process_history([], MockContext())
        
        assert len(messages) == 0
    
    def test_check_type_string(self):
        """测试类型检查 - 字符串"""
        manager = ContextManager()
        
        assert manager._check_type("hello", "string") is True
        assert manager._check_type(123, "string") is False
    
    def test_check_type_number(self):
        """测试类型检查 - 数字"""
        manager = ContextManager()
        
        assert manager._check_type(123, "number") is True
        assert manager._check_type(3.14, "number") is True
        assert manager._check_type("123", "number") is False


class TestStreamingEngine:
    """测试流式引擎"""
    
    @pytest.mark.asyncio
    async def test_stream_text_empty(self):
        """测试空文本流"""
        engine = StreamingEngine()
        
        events = []
        async for event in engine.stream_text(""):
            events.append(event)
        
        assert len(events) == 1  # 只有 done 事件
        assert events[0].event_type == "done"
    
    @pytest.mark.asyncio
    async def test_stream_text_simple(self):
        """测试简单文本流"""
        engine = StreamingEngine()
        
        events = []
        async for event in engine.stream_text("Hello"):
            events.append(event)
        
        # 应该有 content 事件和 done 事件
        assert len(events) >= 2
        assert events[-1].event_type == "done"
    
    def test_extract_code_block(self):
        """测试代码块提取"""
        engine = StreamingEngine()
        
        text = "```python\nprint('hello')\n```"
        chunk, next_pos = engine._extract_code_block(text, 0)
        
        assert "```python" in chunk
        assert chunk.endswith("```")
    
    def test_calculate_delay_code_block(self):
        """测试代码块延迟"""
        engine = StreamingEngine()
        
        delay = engine._calculate_delay("```python", "", 10)
        
        assert delay == engine.config["code_block_delay_ms"]
    
    def test_calculate_delay_sentence_end(self):
        """测试句子结束延迟"""
        engine = StreamingEngine()
        
        delay = engine._calculate_delay("Hello.", "", 6)
        
        assert delay == engine.config["sentence_delay_ms"]


class TestResponseGenerator:
    """测试响应生成器"""
    
    def test_select_role_direct(self):
        """测试角色选择 - DIRECT"""
        generator = ResponseGenerator()
        
        class MockIntent:
            intent_type = IntentType.DIRECT
        
        from model.model_gateway.gateway import LLMRole
        role = generator._select_role(MockIntent())
        
        assert role == LLMRole.FAST
    
    def test_select_role_reasoning(self):
        """测试角色选择 - REASONING"""
        generator = ResponseGenerator()
        
        class MockIntent:
            intent_type = IntentType.REASONING
        
        from model.model_gateway.gateway import LLMRole
        role = generator._select_role(MockIntent())
        
        assert role == LLMRole.QUERY
    
    def test_select_role_default(self):
        """测试角色选择 - 默认值"""
        generator = ResponseGenerator()
        
        from model.model_gateway.gateway import LLMRole
        role = generator._select_role(None)
        
        assert role == LLMRole.QUERY


class TestTurnProcessor:
    """测试对话轮次处理器"""
    
    def test_create_plan(self):
        """测试计划创建"""
        processor = TurnProcessor()
        
        class MockIntent:
            intent_type = IntentType.KNOWLEDGE
            confidence = 0.85
            requires_tools = []
            reasoning_depth = 2
        
        class MockContext:
            token_count = 500
        
        plan = processor._create_plan(MockIntent(), MockContext())
        
        assert plan["intent"] == "KNOWLEDGE"
        assert plan["confidence"] == 0.85
        assert "timestamp" in plan


class TestIntegration:
    """集成测试"""
    
    @pytest.mark.asyncio
    async def test_full_turn_flow(self):
        """测试完整对话流程"""
        processor = TurnProcessor()
        
        # 创建一个请求
        request = TurnRequest(
            query="你好",
            session_id="test_session",
            user_id="test_user",
            conversation_id="test_conv",
            stream=False
        )
        
        # 由于依赖 LLM，这里只测试组件初始化
        assert processor.intent_classifier is not None
        assert processor.context_manager is not None
        assert processor.response_generator is not None
    
    @pytest.mark.asyncio
    async def test_streaming_format(self):
        """测试流式格式"""
        processor = TurnProcessor()
        
        sse = processor._format_sse("content", {"text": "hello"})
        
        assert sse.startswith("data: ")
        assert "content" in sse
        assert "text" in sse


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
