"""Agent 总线协议 — 能力驱动的执行单元。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentMessageKind(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


@dataclass
class AgentBusMessage:
    kind: AgentMessageKind
    correlation_id: str
    capability_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)