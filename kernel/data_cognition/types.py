from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SQLPlan:
    tables: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    sql: str = ""


@dataclass
class DataQueryResult:
    sql: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0
    db_id: str = "default"


@dataclass
class SemanticContext:
    """Resolved semantic mappings for a query."""

    dimension_mappings: dict[str, dict[str, Any]] = field(default_factory=dict)
    metric_defs: dict[str, str] = field(default_factory=dict)
    time_macros: list[dict[str, Any]] = field(default_factory=list)
    resolved_sql_fragments: list[str] = field(default_factory=list)


@dataclass
class CandidateSQL:
    """A candidate SQL statement with ranking metadata."""

    sql: str
    score: float = 0.0
    features: dict[str, Any] = field(default_factory=dict)
    source_template: str = ""


@dataclass
class ValidationResult:
    """Result of post-execution validation."""

    passed: bool
    issues: list[str] = field(default_factory=list)
    severity: str = "info"  # info | warning | critical


@dataclass
class EntityMapping:
    """A natural language mention mapped to a database table."""

    mention: str = ""
    mapped_table: str = ""
    confidence: float = 0.0


@dataclass
class MetricMapping:
    """A natural language metric mapped to a column + aggregation."""

    mention: str = ""
    mapped_column: str = ""
    agg: str = ""  # SUM, COUNT, AVG, MAX, MIN, or empty for raw column


@dataclass
class ParsedFilter:
    """A parsed filter condition."""

    field: str = ""
    operator: str = "="  # =, !=, >, <, >=, <=, LIKE, IN, >=
    value: str = ""
    value_type: str = "string"  # string, number, date, boolean


@dataclass
class SemanticParseResult:
    """Structured semantic parsing output from SemanticParser."""

    entities: list[EntityMapping] = field(default_factory=list)
    metrics: list[MetricMapping] = field(default_factory=list)
    filters: list[ParsedFilter] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    order_by: list[dict[str, str]] = field(default_factory=list)  # [{field, direction}]
    limit: int = 0
    time_window: dict[str, Any] = field(default_factory=dict)


@dataclass
class Explanation:
    """Human-readable explanation of a query."""

    understood_query: str = ""
    tables_used: list[str] = field(default_factory=list)
    filters_applied: list[str] = field(default_factory=list)
    sql: str = ""
    row_count: int = 0
    warnings: list[str] = field(default_factory=list)
