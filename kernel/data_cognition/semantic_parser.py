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
    (
        r"(\d{4})[年-](\d{1,2})[月-](\d{1,2})\s*(?:到|至|~|-)\s*(\d{4})[年-](\d{1,2})[月-](\d{1,2})",
        "date_range",
    ),
    (r"(\d{4})[年-](\d{1,2})[月-](\d{1,2})", "date_exact"),
    (r"(\d{4})[年-](\d{1,2})[月]", "month"),
    (r"(\d{4})年", "year"),
]

# Unit → days mapping for relative time expressions
_TIME_UNIT_DAYS = {"天": 1, "日": 1, "周": 7, "月": 30, "年": 365}

# Comparison operator mapping (Chinese → SQL)
_COMPARISON_OPS = {
    "大于": ">",
    "高于": ">",
    "超过": ">",
    "多于": ">",
    "以上": ">=",
    "小于": "<",
    "低于": "<",
    "少于": "<",
    "以下": "<=",
    "不超过": "<=",
    "等于": "=",
    "为": "=",
    "是": "=",
    "是": "=",
    "不等于": "!=",
    "不是": "!=",
    "大于等于": ">=",
    "小于等于": "<=",
    "至少": ">=",
    "最多": "<=",
}

# Filter value patterns
_VALUE_PATTERNS = [
    # Numeric comparisons: "大于100", "超过50%", "低于1000"
    (r"(?:大于|高于|超过|多于|大于等于|至少)\s*([0-9.]+)%?", ">", "number"),
    (r"(?:小于|低于|少于|小于等于|不超过|最多)\s*([0-9.]+)%?", "<", "number"),
    (r"(?:等于|为|是)\s*([0-9.]+)", "=", "number"),
    (r"(?:不等于|不是)\s*([0-9.]+)", "!=", "number"),
    # Percentage thresholds
    (r"([0-9.]+)%\s*(?:以上|以下|大于|小于|超过)", ">=", "number"),
    # Chinese numerals (simple)
    (r"([一二三四五六七八九十百千万亿]+)", "=", "number"),
]

# Group-by intent patterns
_GROUP_BY_PATTERNS = [
    (r"按(.{1,10}?)(?:统计|分组|汇总|分类|细分|维度)", "entity"),
    (r"(?:每月|按月|按月份|月度)", "month"),
    (r"(?:每年|按年|按年度|年度)", "year"),
    (r"(?:每日|按天|按日|每天)", "day"),
    (r"(?:每周|按周|周)", "week"),
]

# Order-by intent patterns
_ORDER_BY_PATTERNS = [
    # DESC patterns
    (r"(?:最高|最多|最大|最强|最受欢迎)", "DESC"),
    (r"(?:从大到小|降序|倒数)", "DESC"),
    # ASC patterns
    (r"(?:最低|最少|最小|最弱|从少到多)", "ASC"),
    (r"(?:从小到大|升序)", "ASC"),
    # Top-N patterns
    (r"(?:前|Top|top)\s*(\d+)", "DESC"),
]

# Limit patterns (enhanced)
_LIMIT_PATTERNS = [
    r"(?:限制|最多|显示|返回|取)\s*(\d+)",
    r"(?:前|Top|top)\s*(\d+)",
    r"(\d+)\s*(?:条|个|行|名|位|家|种|款)",
    r"(\d+)\s*(?:最多|最少|至少)",
]

# Filter entity/value extraction patterns
_ENTITY_FILTER_PATTERNS = [
    # "北京" "上海" - location values
    (r"([北东南西南东北西北]{1,3})[省市地区]", "location"),
    # "已发货" "未完成" - status values
    (r"(?:状态(?:为|是|等于)?)?(已发货|已取消|未完成|已完成|待支付|已退款|已关闭)", "status"),
    # City/entity mentions: "北京" "上海" followed by business words
    (
        r"(北京|上海|广州|深圳|杭州|成都|重庆|武汉|西安|南京|天津|苏州|长沙|青岛|郑州|大连|沈阳|济南|哈尔滨|福州|昆明|厦门|南昌|贵阳|太原|南宁|乌鲁木齐|兰州)(?:的|地区|城市)?",
        "location",
    ),
]

# Cache configuration
CACHE_PREFIX = "opentrace:semantic_parse"
CACHE_TTL_SECONDS = getattr(settings, "semantic_parse_cache_ttl", 24 * 3600)  # Default 24h


def _make_cache_key(query: str, schema_version: str, table_names: tuple[str, ...]) -> str:
    """Generate deterministic cache key from query and schema context."""
    payload = json.dumps(
        {
            "q": query.strip().lower(),
            "sv": schema_version,
            "tn": sorted(table_names),
        },
        sort_keys=True,
    )
    hash_digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"{CACHE_PREFIX}:{hash_digest}"


def _serialize_result(result: SemanticParseResult) -> dict[str, Any]:
    """Serialize SemanticParseResult to JSON-serializable dict."""
    return {
        "entities": [
            {"mention": e.mention, "mapped_table": e.mapped_table, "confidence": e.confidence}
            for e in result.entities
        ],
        "metrics": [
            {"mention": m.mention, "mapped_column": m.mapped_column, "agg": m.agg}
            for m in result.metrics
        ],
        "filters": [
            {"field": f.field, "operator": f.operator, "value": f.value, "value_type": f.value_type}
            for f in result.filters
        ],
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
        table_columns: dict[str, list[str]] | None = None,
    ) -> None:
        self._schema_linker = SchemaLinker(
            schema_summary=schema_summary,
            table_names=table_names or [],
            table_columns=table_columns or {},
        )
        self._semantic_layer = SemanticLayer(semantic_config or {})
        self._schema_version = schema_version
        self._table_names = tuple(sorted(table_names or []))
        self._table_columns = table_columns or {}
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
        self,
        query: str,
        table_names: list[str],
        database_name: str,
        dialect: SQLDialectSpec | None = None,
    ) -> str | None:
        """Fast-path: detect metadata queries (table_count, table_list, table_schema) and return SQL directly."""

        result = build_structured_database_query(
            query,
            table_names=table_names,
            database_name=database_name,
            dialect=dialect or SQLDialectSpec(name="mysql", schema_name=database_name),
        )
        return result.sql if result else None

    async def parse(
        self,
        query: str,
        dialect: SQLDialectSpec | None = None,
    ) -> SemanticParseResult:
        """Parse a natural language query into structured semantic representation."""
        # Try cache first
        cached = await self._get_cached(query)
        if cached:
            return cached

        # Normal parsing flow
        result = SemanticParseResult()

        # 1. Entity linking
        entities = await self._schema_linker.link_entities(query, table_columns=self._table_columns)
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

        # Extract numeric comparison filters
        for pattern, op, vtype in _VALUE_PATTERNS:
            match = re.search(pattern, query)
            if match:
                val = match.group(1)
                if self._is_time_reference(query[max(0, match.start() - 4) : match.end()]):
                    continue
                if vtype == "number" and not re.match(r"^\d", val):
                    val = str(_chinese_num_to_int(val))
                filters.append(ParsedFilter(field="", operator=op, value=val, value_type=vtype))

        # Extract entity-based filters: "北京的订单" → location=北京
        for pattern, ftype in _ENTITY_FILTER_PATTERNS:
            for match in re.finditer(pattern, query):
                if self._is_time_reference(query[max(0, match.start() - 4) : match.end()]):
                    continue
                val = match.group(1).strip()
                if len(val) < 1 or val in ("的",):
                    continue
                filters.append(
                    ParsedFilter(
                        field="",
                        operator="LIKE" if ftype in ("location", "entity_value") else "=",
                        value=val,
                        value_type=ftype,
                    )
                )

        # Extract multi-condition connectors (AND/OR)
        # If query contains "和""与""且""或", mark subsequent conditions
        if "或" in query and len(filters) >= 2:
            filters[-1].operator = f"OR {filters[-1].operator}"

        return filters

    @staticmethod
    def _is_time_reference(text: str) -> bool:
        """Check if text contains time-related words to avoid false filter matches."""
        time_words = {"最近", "近", "过去", "前", "年", "月", "天", "日", "周", "星期"}
        return any(w in text for w in time_words)

    def _infer_group_by(self, query: str) -> list[str]:
        """Infer GROUP BY fields from query intent."""
        groups: list[str] = []
        seen_types = set()
        _time_units = {"月", "年", "日", "天", "周", "quarter", "季度"}
        for pattern, field_type in _GROUP_BY_PATTERNS:
            if re.search(pattern, query):
                if field_type == "entity":
                    match = re.search(pattern, query)
                    if match:
                        entity = match.group(1).strip()
                        # Skip time unit words — they'll be handled by temporal patterns
                        if entity and entity not in _time_units and entity not in groups:
                            groups.append(entity)
                elif field_type not in seen_types:
                    groups.append(field_type)
                    seen_types.add(field_type)
        return groups

    def _infer_order_by(self, query: str) -> list[dict[str, str]]:
        """Infer ORDER BY clause from query intent."""
        orders: list[dict[str, str]] = []
        for pattern, direction in _ORDER_BY_PATTERNS:
            match = re.search(pattern, query)
            if match:
                field = ""
                # Extract sort field from immediate context (skip time expressions)
                context_start = max(0, match.start() - 6)
                context = query[context_start : match.start()].strip()
                if context and not self._is_time_reference(context):
                    field = context.rstrip("的")
                orders.append({"field": field, "direction": direction})
                break
        return orders

    def _infer_limit(self, query: str) -> int:
        """Infer LIMIT value from query."""
        for pattern in _LIMIT_PATTERNS:
            match = re.search(pattern, query)
            if match:
                return int(match.group(1))
        # Infer implicit limits: "top/前/排名" without explicit number
        if re.search(r"(?:前|top|排名|排行|榜单)", query, re.IGNORECASE):
            return 10  # Default top-N
        return 0

    def _extract_time_window(self, query: str, dialect: SQLDialectSpec | None) -> dict[str, Any]:
        """Extract time window constraints from query."""
        window: dict[str, Any] = {}

        # Try SemanticLayer's structured time extraction first
        try:
            sl_time = SemanticLayer.extract_time_intent(query)
            if sl_time:
                if sl_time.get("days"):
                    window["type"] = "relative_days"
                    window["days"] = sl_time["days"]
                    window["raw"] = sl_time.get("raw", "")
                    window["column_hint"] = sl_time.get("column", "")
                    return window
                elif sl_time.get("start") and sl_time.get("end"):
                    window["type"] = sl_time.get("type", "date_range")
                    window["start"] = sl_time["start"]
                    window["end"] = sl_time["end"]
                    window["raw"] = sl_time.get("raw", "")
                    window["column_hint"] = sl_time.get("column", "")
                    return window
        except Exception:
            pass

        # Fallback: regex-based extraction
        for pattern, ttype in _TIME_FILTER_PATTERNS:
            match = re.search(pattern, query)
            if match:
                groups = match.groups()
                window["type"] = ttype
                window["raw"] = match.group(0)
                window["values"] = groups

                if ttype == "relative_days" and len(groups) >= 2:
                    num, unit = int(groups[0]), groups[1]
                    window["days"] = num * _TIME_UNIT_DAYS.get(unit, 1)

                elif ttype == "date_range" and len(groups) >= 6:
                    window["start"] = f"{groups[0]}-{groups[1].zfill(2)}-{groups[2].zfill(2)}"
                    window["end"] = f"{groups[3]}-{groups[4].zfill(2)}-{groups[5].zfill(2)}"

                elif ttype == "date_exact" and len(groups) >= 3:
                    date_str = f"{groups[0]}-{groups[1].zfill(2)}-{groups[2].zfill(2)}"
                    window["start"] = date_str
                    window["end"] = date_str

                elif ttype == "month" and len(groups) >= 2:
                    window["start"] = f"{groups[0]}-{groups[1].zfill(2)}-01"
                    month = int(groups[1])
                    next_month = 12 if month == 12 else month + 1
                    next_year = int(groups[0]) if month < 12 else int(groups[0]) + 1
                    window["end"] = f"{next_year}-{next_month:02d}-01"

                elif ttype == "year" and len(groups) >= 1:
                    window["start"] = f"{groups[0]}-01-01"
                    window["end"] = f"{int(groups[0]) + 1}-01-01"

                break

        return window


def _chinese_num_to_int(text: str) -> int:
    """Convert simple Chinese numerals to integers (supports 一-十百千万)."""
    cn_map = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
        "百": 100,
        "千": 1000,
        "万": 10000,
        "零": 0,
    }
    if text in cn_map:
        return cn_map[text]
    # Simple composite: "三十" = 30, "五百" = 500
    if len(text) == 2 and text[0] in cn_map and text[1] in cn_map:
        a, b = cn_map[text[0]], cn_map[text[1]]
        if b > a:
            return a * b
        return a + b
    return 0
