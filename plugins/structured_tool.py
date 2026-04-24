"""
Structured tool metadata — documents JSON-schema style inputs for LLM / admin UI.
Runtime execution is wired through tools.registry (async functions).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StructuredToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


CODE_INTERPRETER_SPEC = StructuredToolSpec(
    name="code_interpreter",
    description="在会话沙箱目录下用子进程执行 Python，返回 stdout/stderr 与新文件列表；可选 pip（包名 allowlist）。",
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "packages": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["code"],
    },
)

CHART_GENERATOR_SPEC = StructuredToolSpec(
    name="chart_generator",
    description="根据 JSON 数据生成图表；优先用本工具而非自写绘图代码。",
    input_schema={
        "type": "object",
        "properties": {
            "chart_type": {"type": "string", "enum": ["line", "bar", "scatter", "pie"]},
            "data": {"type": "object"},
            "title": {"type": "string"},
            "format": {"type": "string", "enum": ["png", "html"]},
        },
        "required": ["chart_type", "data"],
    },
)

DATA_ANALYSIS_SPEC = StructuredToolSpec(
    name="data_analysis",
    description="pandas 描述统计、分组聚合、简单清洗；输入为 JSON。",
    input_schema={
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["describe", "aggregate", "clean"]},
            "data": {"type": "string"},
            "group_by": {"type": "string"},
            "agg": {"type": "object"},
        },
        "required": ["operation", "data"],
    },
)

FILE_SANDBOX_SPEC = StructuredToolSpec(
    name="file_sandbox",
    description="会话工作区内读/写/列目录/删文件（相对路径，防穿越）。",
    input_schema={
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["read", "write", "list", "delete"]},
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["operation", "path"],
    },
)
