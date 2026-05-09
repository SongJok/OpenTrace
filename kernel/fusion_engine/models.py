from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    source: str
    data: Any
    confidence: float = 0.5
    source_priority: int = 10
    result_refs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FusionInput:
    query: str
    results: list[ToolResult] = field(default_factory=list)
    adaptive_profile: dict[str, Any] = field(default_factory=dict)
    conversation_history: list[dict[str, str]] = field(default_factory=list)


@dataclass
class FusionOutput:
    merged_context: str
    conflicts: list[str] = field(default_factory=list)
    confidence: float = 0.0
    alternate_contexts: list[str] = field(default_factory=list)
    evidence_map: list[dict[str, Any]] = field(default_factory=list)
    result_refs: list[dict[str, Any]] = field(default_factory=list)
