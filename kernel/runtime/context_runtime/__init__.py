"""
Context Compression Runtime — Prevents prompt inflation in the cognitive pipeline.

Before any context enters an LLM prompt, it passes through this pipeline:
  MemorySelector → EvidenceSelector → ContextRanker → SemanticDistiller → ContextCompressor

This replaces simple string truncation ([:1500]) with semantic compression,
relevance scoring, and intelligent selection.
"""

from kernel.runtime.context_runtime.context_compressor import ContextCompressor
from kernel.runtime.context_runtime.context_ranker import ContextRanker, RankedContextBlock
from kernel.runtime.context_runtime.evidence_selector import EvidenceSelector
from kernel.runtime.context_runtime.memory_selector import MemorySelector
from kernel.runtime.context_runtime.semantic_distiller import SemanticDistiller, DistilledContext

__all__ = [
    "ContextCompressor",
    "ContextRanker",
    "RankedContextBlock",
    "EvidenceSelector",
    "MemorySelector",
    "SemanticDistiller",
    "DistilledContext",
]
