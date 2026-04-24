"""Semantic Parser — structured intent extraction from natural language queries with caching and metrics."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from execution.data.query_intents import build_structured_database_query
from infra.cache.redis_client import get_cache_redis
from infra.config.settings import settings
from infra.observability.metrics import (
    SEMANTIC_PARSE_CACHE_LATENCY,
    SEMANTIC_PARSE_CACHE_TOTAL,
)
from kernel.data_cognition.schema_linker import SchemaLinker
from kernel.data_cognition.semantic_layer import SemanticLayer
from kernel.data_cognition.sql_dialect import SQLDialectSpec
from kernel.data_cognition.types import (
    EntityMapping,
    MetricMapping,
    ParsedFilter,
    SemanticParseResult,
)

# Time-related filter patterns for automatic filter extraction
_TIME_FILTER_PATTERNS = [
    (r"(?:最近|近|过去|前)\s*(\d+)\s*(?:个)?([年月天日周])", "relative_days"),
    (r"(\d{4})[年-](\d{1,2})[月-](\d{1,2})", "date_exact"),
    (r"(\d{4})[年-](\d{1,2})[月]", "month"),
    (r"(\d{4})年", "year"),
]

# Cache configuration
CACHE_PREFIX = "opentrace:semantic_parse"
CACHE_TTL_SECONDS = getattr(settings, "semantic_parse_cache_ttl", 24 * 3600)  # Default 24h


def _make_cache_key(query: str, schema_version: str, table_names: tuple[str, ...]) -> str:
    """Generate deterministic cache key from query and schema context."""
    payload = json.dumps({
        "q": query.strip().lower(),
        "sv": schema_version,
        "tn": sorted(table_names),
    }, sort_keys=True)
    hash_digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"{CACHE_PREFIX}:{hash_digest}"


def _serialize_result(result: SemanticParseResult) -> dict[str, Any]:
    """Serialize SemanticParseResult to JSON-serializable dict."""
    return {
        "entities": [{"mention": e.mention, "mapped_table": e.mapped_table, "confidence": e.confidence} for e in result.entities],
        "metrics": [{"mention": m.mention, "mapped_column": m.mapped_column, "agg": m.agg} for m in result.metrics],
        "filters": [{"field": f.field, "operator": f.operator, "value": f.value, "value_type": f.value_type} for f in result.filters],
        "group_by": result.group_by,
        "order_by": result.order_by,
        "limit": result.limit,
        "time_window": result.time_window,
    }


def _deserialize_result(data: dict[str, Any]) -> SemanticParseResult:
    """Deserialize dict back to SemanticParseResult."""
    result = SemanticParseResult()
    result.entities = [EntityMapping(**e) for e in data.get("entities", [])]
    result.metrics = [MetricMapping(**m) for m in data.get("metrics", [])]
    result.filters = [ParsedFilter(**f) for f in data.get("filters", [])]
    result.group_by = data.get("group_by", [])
    result.order_by = data.get("order_by", [])
    result.limit = data.get("limit", 0)
    result.time_window = data.get("time_window", {})
    return result


class SemanticParser:
    """
    Parses natural language queries into structured semantic representations.

    Combines:
    - Schema linking (entity → table/column mapping)
    - Metric extraction (aggregation intent)
    - Filter extraction (WHERE conditions)
    - Time intent extraction
    - Group/order/limit inference
    
    Features:
    - Redis caching for repeated queries with same schema context
    - Prometheus metrics for cache hit rate and latency monitoring
    """

    def __init__(
        self,
        schema_summary: str = "",
        table_names: list[str] | None = None,
        semantic_config: dict[str, Any] | None = None,
        schema_version: str = "",
        enable_cache: bool = True,
    ) -> None:
        self._schema_linker = SchemaLinker(
            schema_summary=schema_summary, table_names=table_names or [],
        )
        self._semantic_layer = SemanticLayer(semantic_config or {})
        self._schema_version = schema_version
        self._table_names = tuple(sorted(table_names or []))
        self._enable_cache = enable_cache

    async def _get_cached(self, query: str) -> SemanticParseResult | None:
        """Try to fetch parsed result from cache with metrics."""
        if not self._enable_cache:
            return None
        start = time.monotonic()
        result_label = "miss"
        try:
            key = _make_cache_key(query, self._schema_version, self._table_names)
            r = await get_cache_redis()
            raw = await r.get(key)
            if raw:
                data = json.loads(raw)
                result_label = "hit"
                return _deserialize_result(data)
        except Exception:
            result_label = "error"
            # Cache miss or error - fall through to normal parsing
            pass
        finally:
            latency = time.monotonic() - start
            SEMANTIC_PARSE_CACHE_LATENCY.observe(latency)
            SEMANTIC_PARSE_CACHE_TOTAL.labels(result=result_label).inc()
        return None

    async def _set_cache(self, query: str, result: SemanticParseResult) -> None:
        """Store parsed result in cache."""
        if not self._enable_cache:
            return
        try:
            key = _make_cache_key(query, self._schema_version, self._table_names)
            r = await get_cache_redis()
            data = _serialize_result(result)
            await r.setex(key, CACHE_TTL_SECONDS, json.dumps(data))
        except Exception:
            # Cache write failure should not break the main flow
            pass

    def check_structured_intent(
        self, query: str, table_names: list[str], database_name: str,
        dialect: SQLDialectSpec | None = None,
    ) -> str | None:
        """Fast-path: detect metadata queries (table_count, table_list, table_schema) and return SQL directly."""
        from execution.data.query_intents import build_structured_database_query

        result = build_structured_database_query(
            query,
            table_names=table_names,
            database_name=database_name,
            dialect=dialect or SQLDialectSpec(name="mysql", schema_name=database_name),
        )
        return result.sql if result else None

    async def parse(
        self, query: str, dialect: SQLDialectSpec | None = None,
    ) -> SemanticParseResult:
        """Parse a natural language query into structured semantic representation."""
        # Try cache first
        cached = await self._get_cached(query)
        if cached:
            return cached

        # Normal parsing flow
        result = SemanticParseResult()

        # 1. Entity linking
        entities = await self._schema_linker.link_entities(query)
        result.entities = entities

        # 2. Metric linking
        metrics = await self._schema_linker.link_metrics(query)
        result.metrics = metrics

        # 3. Filter extraction
        result.filters = self._extract_filters(query)

        # 4. Group by inference
        result.group_by = self._infer_group_by(query)

        # 5. Order by inference
        result.order_by = self._infer_order_by(query)

        # 6. Limit inference
        result.limit = self._infer_limit(query)

        # 7. Time window extraction
        result.time_window = self._extract_time_window(query, dialect)

        # Cache the result for future use
        await self._set_cache(query, result)

        return result

    def _extract_filters(self, query: str) -> list[ParsedFilter]:
        """Extract filter conditions from query text."""
        filters: list[ParsedFilter] = []
        # TODO: Implement filter extraction logic
        return filters

    def _infer_group_by(self, query: str) -> list[str]:
        """Infer GROUP BY fields from query intent."""
        # TODO: Implement group-by inference
        return []

    def _infer_order_by(self, query: str) -> list[dict[str, str]]:
        """Infer ORDER BY clause from query intent."""
        # TODO: Implement order-by inference
        return []

    def _infer_limit(self, query: str) -> int:
        """Infer LIMIT value from query."""
        match = re.search(r"(?:限制|最多|显示|返回)\s*(\d+)", query)
        if match:
            return int(match.group(1))
        return 0

    def _extract_time_window(self, query: str, dialect: SQLDialectSpec | None) -> dict[str, Any]:
        """Extract time window constraints from query."""
        window: dict[str, Any] = {}
        for pattern, ttype in _TIME_FILTER_PATTERNS:
            match = re.search(pattern, query)
            if match:
                window["type"] = ttype
                window["raw"] = match.group(0)
                window["values"] = match.groups()
                break
        return window
