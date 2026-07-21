"""语义解析器 — 从自然语言查询抽取结构化意图（含缓存与指标）。"""

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

# 时间相关过滤模式，用于自动过滤条件提取
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

# 时间单位 → 天数映射
_TIME_UNIT_DAYS = {"天": 1, "日": 1, "周": 7, "月": 30, "年": 365}

# 比较运算符映射（中文 → SQL）
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

# 过滤值模式
_VALUE_PATTERNS = [
    # 数值比较："大于100"、"超过50%"、"低于1000"
    (r"(?:大于|高于|超过|多于|大于等于|至少)\s*([0-9.]+)%?", ">", "number"),
    (r"(?:小于|低于|少于|小于等于|不超过|最多)\s*([0-9.]+)%?", "<", "number"),
    (r"(?:等于|为|是)\s*([0-9.]+)", "=", "number"),
    (r"(?:不等于|不是)\s*([0-9.]+)", "!=", "number"),
    # 百分比阈值
    (r"([0-9.]+)%\s*(?:以上|以下|大于|小于|超过)", ">=", "number"),
    # 中文数字（简单）
    (r"([一二三四五六七八九十百千万亿]+)", "=", "number"),
]

# 分组意图模式
_GROUP_BY_PATTERNS = [
    (r"按(.{1,10}?)(?:统计|分组|汇总|分类|细分|维度)", "entity"),
    (r"(?:每月|按月|按月份|月度)", "month"),
    (r"(?:每年|按年|按年度|年度)", "year"),
    (r"(?:每日|按天|按日|每天)", "day"),
    (r"(?:每周|按周|周)", "week"),
]

# 排序意图模式
_ORDER_BY_PATTERNS = [
    # 降序模式
    (r"(?:最高|最多|最大|最强|最受欢迎)", "DESC"),
    (r"(?:从大到小|降序|倒数)", "DESC"),
    # 升序模式
    (r"(?:最低|最少|最小|最弱|从少到多)", "ASC"),
    (r"(?:从小到大|升序)", "ASC"),
    # Top-N 模式
    (r"(?:前|Top|top)\s*(\d+)", "DESC"),
]

# 限制模式（增强版）
_LIMIT_PATTERNS = [
    r"(?:限制|最多|显示|返回|取)\s*(\d+)",
    r"(?:前|Top|top)\s*(\d+)",
    r"(\d+)\s*(?:条|个|行|名|位|家|种|款)",
    r"(\d+)\s*(?:最多|最少|至少)",
]

# 过滤实体/值提取模式
_ENTITY_FILTER_PATTERNS = [
    # "北京" "上海" - 地点值
    (r"([北东南西南东北西北]{1,3})[省市地区]", "location"),
    # "已发货" "未完成" - 状态值
    (r"(?:状态(?:为|是|等于)?)?(已发货|已取消|未完成|已完成|待支付|已退款|已关闭)", "status"),
    # 城市/实体提及："北京" "上海" 后接业务词
    (
        r"(北京|上海|广州|深圳|杭州|成都|重庆|武汉|西安|南京|天津|苏州|长沙|青岛|郑州|大连|沈阳|济南|哈尔滨|福州|昆明|厦门|南昌|贵阳|太原|南宁|乌鲁木齐|兰州)(?:的|地区|城市)?",
        "location",
    ),
]

# 缓存配置
CACHE_PREFIX = "opentrace:semantic_parse"
CACHE_TTL_SECONDS = getattr(settings, "semantic_parse_cache_ttl", 24 * 3600)  # 默认 24 小时


def _make_cache_key(query: str, schema_version: str, table_names: tuple[str, ...]) -> str:
    """根据查询和模式上下文生成确定性缓存键。"""
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
    """将 SemanticParseResult 序列化为可 JSON 化的字典。"""
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
    """将字典反序列化为 SemanticParseResult。"""
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
    将自然语言查询解析为结构化语义表示。

    组合：
    - 模式链接（实体 → 表/列映射）
    - 指标提取（聚合意图）
    - 过滤条件提取（WHERE 条件）
    - 时间意图提取
    - 分组/排序/限制推断

    特性：
    - Redis 缓存，用于相同模式上下文的重复查询
    - Prometheus 指标，用于缓存命中率和延迟监控
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
        """尝试从缓存获取解析结果，附带指标监控。"""
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
            # 缓存未命中或出错 - 继续正常解析
            pass
        finally:
            latency = time.monotonic() - start
            SEMANTIC_PARSE_CACHE_LATENCY.observe(latency)
            SEMANTIC_PARSE_CACHE_TOTAL.labels(result=result_label).inc()
        return None

    async def _set_cache(self, query: str, result: SemanticParseResult) -> None:
        """将解析结果存入缓存。"""
        if not self._enable_cache:
            return
        try:
            key = _make_cache_key(query, self._schema_version, self._table_names)
            r = await get_cache_redis()
            data = _serialize_result(result)
            await r.setex(key, CACHE_TTL_SECONDS, json.dumps(data))
        except Exception:
            # 缓存写入失败不应中断主流程
            pass

    def check_structured_intent(
        self,
        query: str,
        table_names: list[str],
        database_name: str,
        dialect: SQLDialectSpec | None = None,
    ) -> str | None:
        """快速路径：检测元数据查询（table_count、table_list、table_schema）并直接返回 SQL。"""

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
        """将自然语言查询解析为结构化语义表示。"""
        # 先尝试缓存
        cached = await self._get_cached(query)
        if cached:
            return cached

        # 正常解析流程
        result = SemanticParseResult()

        # 1. 实体链接
        entities = await self._schema_linker.link_entities(query, table_columns=self._table_columns)
        result.entities = entities

        # 2. 指标链接
        metrics = await self._schema_linker.link_metrics(query)
        result.metrics = metrics

        # 3. 过滤条件提取
        result.filters = self._extract_filters(query)

        # 4. 分组推断
        result.group_by = self._infer_group_by(query)

        # 5. 排序推断
        result.order_by = self._infer_order_by(query)

        # 6. 限制推断
        result.limit = self._infer_limit(query)

        # 7. 时间窗口提取
        result.time_window = self._extract_time_window(query, dialect)

        # 缓存结果供后续使用
        await self._set_cache(query, result)

        return result

    def _extract_filters(self, query: str) -> list[ParsedFilter]:
        """从查询文本中提取过滤条件。"""
        filters: list[ParsedFilter] = []

        # 提取数值比较过滤条件
        for pattern, op, vtype in _VALUE_PATTERNS:
            match = re.search(pattern, query)
            if match:
                val = match.group(1)
                if self._is_time_reference(query[max(0, match.start() - 4) : match.end()]):
                    continue
                if vtype == "number" and not re.match(r"^\d", val):
                    val = str(_chinese_num_to_int(val))
                filters.append(ParsedFilter(field="", operator=op, value=val, value_type=vtype))

        # 提取基于实体的过滤条件："北京的订单" → location=北京
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

        # 提取多条件连接词（AND/OR）
        # 如果查询包含"和""与""且""或"，标记后续条件
        if "或" in query and len(filters) >= 2:
            filters[-1].operator = f"OR {filters[-1].operator}"

        return filters

    @staticmethod
    def _is_time_reference(text: str) -> bool:
        """检查文本是否包含时间相关词汇，以避免误匹配过滤条件。"""
        time_words = {"最近", "近", "过去", "前", "年", "月", "天", "日", "周", "星期"}
        return any(w in text for w in time_words)

    def _infer_group_by(self, query: str) -> list[str]:
        """从查询意图推断 GROUP BY 字段。"""
        groups: list[str] = []
        seen_types = set()
        _time_units = {"月", "年", "日", "天", "周", "quarter", "季度"}
        for pattern, field_type in _GROUP_BY_PATTERNS:
            if re.search(pattern, query):
                if field_type == "entity":
                    match = re.search(pattern, query)
                    if match:
                        entity = match.group(1).strip()
                        # 跳过时间单位词 — 它们将由时间模式处理
                        if entity and entity not in _time_units and entity not in groups:
                            groups.append(entity)
                elif field_type not in seen_types:
                    groups.append(field_type)
                    seen_types.add(field_type)
        return groups

    def _infer_order_by(self, query: str) -> list[dict[str, str]]:
        """从查询意图推断 ORDER BY 子句。"""
        orders: list[dict[str, str]] = []
        for pattern, direction in _ORDER_BY_PATTERNS:
            match = re.search(pattern, query)
            if match:
                field = ""
                # 从紧邻上下文提取排序字段（跳过时间表达式）
                context_start = max(0, match.start() - 6)
                context = query[context_start : match.start()].strip()
                if context and not self._is_time_reference(context):
                    field = context.rstrip("的")
                orders.append({"field": field, "direction": direction})
                break
        return orders

    def _infer_limit(self, query: str) -> int:
        """从查询推断 LIMIT 值。"""
        for pattern in _LIMIT_PATTERNS:
            match = re.search(pattern, query)
            if match:
                return int(match.group(1))
        # 推断隐式限制："top/前/排名" 无显式数字
        if re.search(r"(?:前|top|排名|排行|榜单)", query, re.IGNORECASE):
            return 10  # 默认 Top-N
        return 0

    def _extract_time_window(self, query: str, dialect: SQLDialectSpec | None) -> dict[str, Any]:
        """从查询中提取时间窗口约束。"""
        window: dict[str, Any] = {}

        # 优先尝试 SemanticLayer 的结构化时间提取
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

        # 回退：基于正则的提取
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
    """将简单中文数字转换为整数（支持 一-十百千万）。"""
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
    # 简单组合："三十" = 30, "五百" = 500
    if len(text) == 2 and text[0] in cn_map and text[1] in cn_map:
        a, b = cn_map[text[0]], cn_map[text[1]]
        if b > a:
            return a * b
        return a + b
    return 0
