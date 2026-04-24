from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4
import time


class CognitiveEventType(str, Enum):
    PLANNING = "planning"
    EXECUTION = "execution"
    EVIDENCE = "evidence"
    CRITIC = "critic"
    FEEDBACK = "feedback"
    LEARNING = "learning"


@dataclass(slots=True)
class CognitiveEvent:
    event_type: CognitiveEventType
    trace_id: str
    session_id: str | None = None
    user_id: str | None = None
    request_id: str | None = None
    timestamp: float = field(default_factory=lambda: time.time())
    causation_id: str | None = None
    event_id: str = field(default_factory=lambda: uuid4().hex)
    source: str | None = None
    actor: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "causation_id": self.causation_id,
            "source": self.source,
            "actor": self.actor,
            "payload": self.payload,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CognitiveEvent":
        return cls(
            event_id=str(data.get("event_id") or uuid4().hex),
            event_type=CognitiveEventType(str(data["event_type"])),
            trace_id=str(data["trace_id"]),
            session_id=data.get("session_id"),
            user_id=data.get("user_id"),
            request_id=data.get("request_id"),
            timestamp=float(data.get("timestamp") or time.time()),
            causation_id=data.get("causation_id"),
            source=data.get("source"),
            actor=data.get("actor"),
            payload=dict(data.get("payload") or {}),
            schema_version=int(data.get("schema_version") or 1),
        )
