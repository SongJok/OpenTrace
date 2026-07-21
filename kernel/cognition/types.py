"""认知层共享类型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class CapabilityLevel(Enum):
    FULL = "full"
    PARTIAL = "partial"
    DELEGATE = "delegate"
    UNAVAILABLE = "unavailable"


class TaskDomain(Enum):
    DATA_QUERY = "data_query"
    DOCUMENT_RETRIEVAL = "document_retrieval"
    WEB_SEARCH = "web_search"
    TOOL_EXECUTION = "tool_execution"
    GENERAL_QA = "general_qa"
    ANALYSIS = "analysis"
    CODE_GENERATION = "code_generation"


@dataclass
class CapabilityAssessment:
    domain: TaskDomain
    level: CapabilityLevel
    confidence: float
    required_agents: list[str]
    expected_latency_ms: int
    constraints: list[str] = field(default_factory=list)
    fallback_strategy: str | None = None
    reasoning: str = ""


@dataclass
class SelfState:
    timestamp: datetime
    enabled_agents: list[str]
    available_tools: list[str]
    connected_data_sources: list[dict[str, str]]
    model_routing: dict[str, str]
    rate_limit_remaining: int | None = None
    degraded_mode: bool = False
    degraded_reason: str | None = None


@dataclass
class GroundedEntity:
    original_term: str
    entity_type: str
    canonical_name: str
    mappings: dict[str, Any]
    confidence: float
    alternatives: list[str] = field(default_factory=list)


@dataclass
class Hypothesis:
    id: str
    statement: str
    confidence: float
    source: str
    validation_status: str = "pending"
    evidence_for: list[str] = field(default_factory=list)
    evidence_against: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
