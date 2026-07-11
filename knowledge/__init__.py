"""Knowledge orchestration domain.

This package turns raw enterprise assets into governed, traceable knowledge
objects.  RAG remains a retrieval adapter; knowledge objects are the source of
truth for orchestrated queries.
"""

from knowledge.domain import KnowledgeAuthority, KnowledgeStatus, KnowledgeType

__all__ = ["KnowledgeAuthority", "KnowledgeStatus", "KnowledgeType"]
