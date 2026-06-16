"""能力本体 — 能力类与模式的形式化定义。

将 profiler._SEED_DATA 中的隐式知识编码为显式枚举与类型化属性模式；
供 knowledge_graph 与 reasoner 校验与推理。
"""

from __future__ import annotations

from enum import Enum
from typing import TypedDict


class CapabilityClass(str, Enum):
    """系统已知的全部 14 种能力类型的规范枚举。"""

    DATA_QUERY = "data.query"
    DATA_ANALYSIS = "data.analysis"
    WEB_SEARCH = "web.search"
    RAG_RETRIEVE = "rag.retrieve"
    TOOL_DATETIME = "tool.datetime"
    TOOL_WEATHER = "tool.weather"
    TOOL_CALCULATOR = "tool.calculator"
    PYTHON_EXECUTE = "python.execute"
    CHART_GENERATE = "chart.generate"
    MEMORY_RETRIEVE = "memory.retrieve"
    ENTITY_RESOLUTION = "entity.resolution"
    VISION_ANALYZE = "vision.analyze"
    SKILLS_EXECUTE = "skills.execute"


class ResourceCategory(str, Enum):
    CPU = "cpu"
    IO = "io"
    GPU = "gpu"


class QualityDimension(str, Enum):
    ACCURACY = "accuracy"
    COMPLETENESS = "completeness"
    FRESHNESS = "freshness"
    RELEVANCE = "relevance"


class LatencyProfile(TypedDict, total=False):
    expected_ms: int
    p50_ms: int
    p95_ms: int


class ResourceProfile(TypedDict, total=False):
    resource_type: str
    max_parallel: int
    requires_exclusive: bool


class QualityProfile(TypedDict, total=False):
    accuracy: float
    freshness_requirement: str  # "realtime" | "hourly" | "daily" | "static"（实时|每小时|每天|静态）
    evidence_grade: str  # "weak" | "moderate" | "strong" | "definitive"（弱|中等|强|确定）


# 模式表 — 从 profiler._SEED_DATA 派生并在此形式化。
# 将每个 CapabilityClass 映射到其延迟、资源与质量画像。

_CAPABILITY_SCHEMAS: dict[CapabilityClass, dict] = {
    CapabilityClass.DATA_QUERY: {
        "latency": LatencyProfile(expected_ms=3000, p50_ms=2000, p95_ms=8000),
        "resource": ResourceProfile(resource_type="cpu", max_parallel=3, requires_exclusive=False),
        "quality": QualityProfile(accuracy=0.92, freshness_requirement="hourly", evidence_grade="strong"),
    },
    CapabilityClass.DATA_ANALYSIS: {
        "latency": LatencyProfile(expected_ms=5000, p50_ms=3500, p95_ms=12000),
        "resource": ResourceProfile(resource_type="cpu", max_parallel=2, requires_exclusive=False),
        "quality": QualityProfile(accuracy=0.85, freshness_requirement="hourly", evidence_grade="moderate"),
    },
    CapabilityClass.WEB_SEARCH: {
        "latency": LatencyProfile(expected_ms=2500, p50_ms=1800, p95_ms=6000),
        "resource": ResourceProfile(resource_type="io", max_parallel=5, requires_exclusive=False),
        "quality": QualityProfile(accuracy=0.80, freshness_requirement="realtime", evidence_grade="moderate"),
    },
    CapabilityClass.RAG_RETRIEVE: {
        "latency": LatencyProfile(expected_ms=1500, p50_ms=800, p95_ms=4000),
        "resource": ResourceProfile(resource_type="io", max_parallel=4, requires_exclusive=False),
        "quality": QualityProfile(accuracy=0.88, freshness_requirement="daily", evidence_grade="strong"),
    },
    CapabilityClass.TOOL_DATETIME: {
        "latency": LatencyProfile(expected_ms=300, p50_ms=150, p95_ms=800),
        "resource": ResourceProfile(resource_type="cpu", max_parallel=10, requires_exclusive=False),
        "quality": QualityProfile(accuracy=0.99, freshness_requirement="realtime", evidence_grade="definitive"),
    },
    CapabilityClass.TOOL_WEATHER: {
        "latency": LatencyProfile(expected_ms=1500, p50_ms=1000, p95_ms=3000),
        "resource": ResourceProfile(resource_type="io", max_parallel=5, requires_exclusive=False),
        "quality": QualityProfile(accuracy=0.95, freshness_requirement="realtime", evidence_grade="strong"),
    },
    CapabilityClass.TOOL_CALCULATOR: {
        "latency": LatencyProfile(expected_ms=200, p50_ms=100, p95_ms=500),
        "resource": ResourceProfile(resource_type="cpu", max_parallel=10, requires_exclusive=False),
        "quality": QualityProfile(accuracy=0.99, freshness_requirement="static", evidence_grade="definitive"),
    },
    CapabilityClass.PYTHON_EXECUTE: {
        "latency": LatencyProfile(expected_ms=8000, p50_ms=5000, p95_ms=20000),
        "resource": ResourceProfile(resource_type="cpu", max_parallel=1, requires_exclusive=True),
        "quality": QualityProfile(accuracy=0.85, freshness_requirement="static", evidence_grade="strong"),
    },
    CapabilityClass.CHART_GENERATE: {
        "latency": LatencyProfile(expected_ms=6000, p50_ms=4000, p95_ms=15000),
        "resource": ResourceProfile(resource_type="gpu", max_parallel=2, requires_exclusive=False),
        "quality": QualityProfile(accuracy=0.82, freshness_requirement="hourly", evidence_grade="strong"),
    },
    CapabilityClass.MEMORY_RETRIEVE: {
        "latency": LatencyProfile(expected_ms=500, p50_ms=300, p95_ms=1500),
        "resource": ResourceProfile(resource_type="io", max_parallel=5, requires_exclusive=False),
        "quality": QualityProfile(accuracy=0.90, freshness_requirement="daily", evidence_grade="moderate"),
    },
    CapabilityClass.ENTITY_RESOLUTION: {
        "latency": LatencyProfile(expected_ms=800, p50_ms=500, p95_ms=2000),
        "resource": ResourceProfile(resource_type="cpu", max_parallel=5, requires_exclusive=False),
        "quality": QualityProfile(accuracy=0.87, freshness_requirement="daily", evidence_grade="moderate"),
    },
    CapabilityClass.VISION_ANALYZE: {
        "latency": LatencyProfile(expected_ms=5000, p50_ms=3500, p95_ms=12000),
        "resource": ResourceProfile(resource_type="gpu", max_parallel=2, requires_exclusive=True),
        "quality": QualityProfile(accuracy=0.80, freshness_requirement="realtime", evidence_grade="moderate"),
    },
    CapabilityClass.SKILLS_EXECUTE: {
        "latency": LatencyProfile(expected_ms=3000, p50_ms=2000, p95_ms=10000),
        "resource": ResourceProfile(resource_type="cpu", max_parallel=3, requires_exclusive=False),
        "quality": QualityProfile(accuracy=0.78, freshness_requirement="static", evidence_grade="moderate"),
    },
}


def get_capability_schema(cap_type: str) -> dict:
    """返回能力类型字符串的形式化模式。

    返回延迟、资源与质量画像。
    对未知类型回退到合理的默认值。
    """
    try:
        cap_class = CapabilityClass(cap_type)
    except ValueError:
        return {
            "latency": LatencyProfile(expected_ms=2000, p50_ms=1500, p95_ms=5000),
            "resource": ResourceProfile(resource_type="cpu", max_parallel=3, requires_exclusive=False),
            "quality": QualityProfile(accuracy=0.80, freshness_requirement="daily", evidence_grade="moderate"),
        }
    return dict(_CAPABILITY_SCHEMAS.get(cap_class, {}))
