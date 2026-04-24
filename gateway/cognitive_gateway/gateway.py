"""
Cognitive Gateway — uses the new CognitiveOrchestrator.
Handles session load/persist around the orchestrator call.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from infra.cache.redis_client import get_session_redis
from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from kernel.orchestrator import (
    CognitiveOrchestrator,
    OrchestratorRequest,
    OrchestratorResponse,
)

logger = get_logger(__name__)
tracer = get_tracer(__name__)

SESSION_TTL = 3600
SESSION_KEY = "opentrace:session:{session_id}"


# ---------------------------------------------------------------------------
# Backwards-compat shim — chat.py imports KernelResponse
# ---------------------------------------------------------------------------
class KernelResponse:
    def __init__(self, resp: OrchestratorResponse) -> None:
        self.content = resp.content
        self.decision_type = resp.route
        self.passed_validation = resp.passed_validation
        self.validation_score = resp.validation_score
        self.metadata = resp.metadata


class CognitiveGateway:
    """
    Session-aware entry point to the CognitiveOrchestrator.
    Loads conversation history from Redis, passes it to the orchestrator,
    then persists the updated session.
    """

    def __init__(self, orchestrator: Optional[CognitiveOrchestrator] = None) -> None:
        self.orchestrator = orchestrator or CognitiveOrchestrator()

    async def handle(
        self,
        query: str,
        session_id: str,
        user_id: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> KernelResponse:
        with tracer.start_as_current_span("cognitive_gateway.handle") as span:
            span.set_attribute("session.id", session_id)
            span.set_attribute("user.id", user_id)

            # Load session
            session = await self._load_session(session_id)
            history: list[dict[str, str]] = session.get("history", [])

            # Build orchestrator request
            request = OrchestratorRequest(
                query=query,
                session_id=session_id,
                user_id=user_id,
                history=history,
                metadata=metadata or {},
            )

            # Process through orchestrator
            response: OrchestratorResponse = await self.orchestrator.process(request)

            # Persist session
            history.append({"role": "user", "content": query})
            history.append({"role": "assistant", "content": response.content})
            session["history"] = history[-40:]
            session["last_active"] = time.time()
            session["last_route"] = response.route
            await self._save_session(session_id, session)

            return KernelResponse(response)

    async def _load_session(self, session_id: str) -> dict[str, Any]:
        r = await get_session_redis()
        key = SESSION_KEY.format(session_id=session_id)
        raw = await r.get(key)
        if raw:
            return json.loads(raw)
        return {"session_id": session_id, "history": [], "created": time.time()}

    async def _save_session(self, session_id: str, data: dict[str, Any]) -> None:
        r = await get_session_redis()
        key = SESSION_KEY.format(session_id=session_id)
        await r.setex(key, SESSION_TTL, json.dumps(data))
