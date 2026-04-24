"""
CognitiveKernel — thin shim kept for backwards compatibility.
All real logic now lives in CognitiveOrchestrator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from kernel.orchestrator import CognitiveOrchestrator, OrchestratorRequest

logger = get_logger(__name__)
tracer = get_tracer(__name__)


@dataclass
class KernelRequest:
    query: str
    session_id: str = ""
    context: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KernelResponse:
    content: str
    decision_type: str
    passed_validation: bool = True
    validation_score: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


class CognitiveKernel:
    """
    Backwards-compatible wrapper around CognitiveOrchestrator.
    New code should use CognitiveOrchestrator directly.
    """

    def __init__(self, orchestrator: Optional[CognitiveOrchestrator] = None) -> None:
        self._orchestrator = orchestrator or CognitiveOrchestrator()

    async def process(self, request: KernelRequest) -> KernelResponse:
        with tracer.start_as_current_span("cognitive_kernel.process") as span:
            span.set_attribute("session.id", request.session_id)

            orch_req = OrchestratorRequest(
                query=request.query,
                session_id=request.session_id,
                history=request.history,
                metadata=request.metadata,
            )
            resp = await self._orchestrator.process(orch_req)

            return KernelResponse(
                content=resp.content,
                decision_type=resp.route,
                passed_validation=resp.passed_validation,
                validation_score=resp.validation_score,
                metadata=resp.metadata,
            )
