from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from gateway.api_gateway.routers.admin import get_current_admin_user
from infra.message_bus.events import CognitiveEventType
from infra.message_bus.replay import replay_service
from infra.storage.models import User

router = APIRouter()


@router.get("/cognitive-events/replay")
async def replay_cognitive_events(
    trace_id: str = Query(..., min_length=1),
    limit: int = Query(200, ge=1, le=2000),
    event_type: list[str] | None = Query(default=None),
    current_user: User = Depends(get_current_admin_user),
) -> dict:
    parsed_types: list[CognitiveEventType] | None = None
    if event_type:
        parsed_types = []
        for raw in event_type:
            try:
                parsed_types.append(CognitiveEventType(raw))
            except Exception:
                continue
        if not parsed_types:
            parsed_types = None
    summary = await replay_service.summary(trace_id=trace_id, limit=limit, event_types=parsed_types)
    return {"status": "ok", **summary}
