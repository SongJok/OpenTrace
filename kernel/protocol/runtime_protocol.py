"""运行域协议 — 执行、证据、制品。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RuntimePhase(str, Enum):
    PROJECTION = "projection"
    EXECUTE = "execute"
    EVIDENCE = "evidence"
    FUSION = "fusion"
    CRITIC = "critic"
    ARTIFACT = "artifact"


@dataclass
class RuntimeEnvelope:
    phase: RuntimePhase
    task_id: str
    session_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    version: str = "runtime_protocol_v1"


@dataclass
class ExecutionUnitRef:
    """Capability-driven execution unit — not necessarily a named Agent."""

    unit_id: str
    capability_type: str
    strategy: str = ""
    params: dict[str, Any] = field(default_factory=dict)