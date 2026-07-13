"""
OpenTrace Cognitive Core - 认知内核核心

参考 ChatGPT/o1 架构设计的认知计算内核
"""

from .turn_processor import TurnProcessor, TurnRequest, TurnResponse
from .intent_classifier import IntentClassifier, IntentClassification, IntentType
from .context_manager import ContextManager, ContextWindow
from .response_generator import ResponseGenerator, GenerationResult
from .streaming_engine import StreamingEngine, StreamEvent

__all__ = [
    # Turn Processing
    "TurnProcessor",
    "TurnRequest",
    "TurnResponse",
    # Intent Classification
    "IntentClassifier",
    "IntentClassification",
    "IntentType",
    # Context Management
    "ContextManager",
    "ContextWindow",
    # Response Generation
    "ResponseGenerator",
    "GenerationResult",
    # Streaming
    "StreamingEngine",
    "StreamEvent",
]
