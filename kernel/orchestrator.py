"""
Backward compatibility wrapper for orchestrator_v4.
Exports v4 classes under the old names for legacy imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from legacy.v4.orchestrator import (
    CognitiveOrchestratorV4,
    OrchestratorV4Request,
)


@dataclass
class OrchestratorRequest:
    """Legacy request type, compatible with v4."""

    query: str
    session_id: str = ""
    user_id: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestratorResponse:
    """Legacy response type, compatible with v4."""

    content: str
    route: str
    strategy: str = "direct"
    passed_validation: bool = True
    validation_score: float = 1.0
    hallucination_risk: float = 0.0
    intent_category: str = "general"
    metadata: dict[str, Any] = field(default_factory=dict)
    execution_graph: Any = None


class CognitiveOrchestrator:
    """
    Legacy orchestrator wrapper for CognitiveOrchestratorV4.
    Maintains backward compatibility for existing imports.
    """

    def __init__(
        self,
        intent_engine=None,
        policy_engine=None,
        reasoning_engine=None,
        meta_cognition=None,
        stream_event_cb=None,
    ) -> None:
        """Accept legacy constructor args but ignore them (v4 uses different structure)."""
        self._orchestrator = CognitiveOrchestratorV4()
        self._stream_event_cb = stream_event_cb

    async def process(self, request: OrchestratorRequest) -> OrchestratorResponse:
        """Process a request using v4 orchestrator."""
        # Convert legacy request to v4 request
        v4_request = OrchestratorV4Request(
            query=request.query,
            session_id=request.session_id,
            user_id=request.user_id,
            history=request.history,
            metadata=request.metadata,
        )

        # Process with v4 orchestrator
        v4_response = await self._orchestrator.process(v4_request)

        # Extract execution_graph from metadata if present
        execution_graph = v4_response.metadata.get("execution_graph")

        # Convert v4 response to legacy response
        return OrchestratorResponse(
            content=v4_response.content,
            route=v4_response.route,
            strategy=v4_response.strategy,
            passed_validation=v4_response.passed_validation,
            validation_score=v4_response.validation_score,
            hallucination_risk=v4_response.hallucination_risk,
            intent_category=v4_response.intent_category,
            metadata=v4_response.metadata,
            execution_graph=execution_graph,
        )

    async def resume(self, session_id: str, step_index: int = 0) -> OrchestratorResponse:
        """Resume a session - not fully implemented in v4, return fallback."""
        # This is a minimal implementation for compatibility
        return OrchestratorResponse(
            content="Session resume functionality is not fully supported in v4 orchestrator.",
            route="fallback",
            strategy="direct",
            passed_validation=False,
            validation_score=0.0,
            hallucination_risk=0.0,
            intent_category="system",
            metadata={"note": "resume_not_supported_v4"},
        )
