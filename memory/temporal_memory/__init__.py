"""
TemporalMemory — Time-aware memory index for recency-weighted retrieval.

Enhances the existing memory layer with temporal decay and time-based
filtering, so recent events are weighted higher in retrieval.
"""

from memory.temporal_memory.temporal_index import TemporalMemoryIndex

__all__ = ["TemporalMemoryIndex"]
