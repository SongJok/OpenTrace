"""运行时回合内持久化认知状态演化。"""

from kernel.runtime.cognitive_state.store import CognitiveRuntimeState, get_or_create_runtime_state

__all__ = ["CognitiveRuntimeState", "get_or_create_runtime_state"]