from __future__ import annotations

from typing import Any

from infra.message_bus.cognitive_event_bus import CognitiveEventBus, cognitive_event_bus
from infra.message_bus.events import CognitiveEvent, CognitiveEventType


class CognitiveEventReplayService:
    def __init__(self, bus: CognitiveEventBus = cognitive_event_bus) -> None:
        self.bus = bus

    async def replay(self, trace_id: str, limit: int = 200) -> list[CognitiveEvent]:
        return await self.bus.replay(trace_id=trace_id, limit=limit)

    @staticmethod
    def _build_summary(events: list[CognitiveEvent]) -> dict[str, Any]:
        if not events:
            return {
                "first_timestamp": None,
                "last_timestamp": None,
                "duration_ms": 0,
                "stage_counts": {},
                "has_critic": False,
                "has_learning": False,
            }
        first_ts = min(e.timestamp for e in events)
        last_ts = max(e.timestamp for e in events)
        stage_counts: dict[str, int] = {}
        for event in events:
            stage_counts[event.event_type.value] = stage_counts.get(event.event_type.value, 0) + 1
        return {
            "first_timestamp": first_ts,
            "last_timestamp": last_ts,
            "duration_ms": int(max(0.0, (last_ts - first_ts) * 1000)),
            "stage_counts": stage_counts,
            "has_critic": any(e.event_type == CognitiveEventType.CRITIC for e in events),
            "has_learning": any(e.event_type == CognitiveEventType.LEARNING for e in events),
        }

    async def summary(
        self,
        trace_id: str,
        limit: int = 200,
        event_types: list[CognitiveEventType] | None = None,
    ) -> dict[str, Any]:
        events = await self.replay(trace_id=trace_id, limit=limit)
        if event_types:
            allowed = {e.value for e in event_types}
            events = [e for e in events if e.event_type.value in allowed]
        timeline = [e.to_dict() for e in events]
        return {
            "trace_id": trace_id,
            "count": len(events),
            "event_types": [e.event_type.value for e in events],
            "session_id": events[0].session_id if events else None,
            "summary": self._build_summary(events),
            "timeline": timeline,
        }


replay_service = CognitiveEventReplayService()
