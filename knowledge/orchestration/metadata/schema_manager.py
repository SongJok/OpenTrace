"""知识页面 Schema 与 Obsidian Markdown 模板。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class PageSchema:
    name: str
    required_fields: tuple[str, ...]
    sections: tuple[tuple[str, str], ...]


DEFAULT_SCHEMAS: dict[str, PageSchema] = {
    "overview": PageSchema("overview", ("title", "description"), (("概览", "description"),)),
    "concept": PageSchema(
        "concept",
        ("title", "description", "definition"),
        (("定义", "definition"), ("关键特征", "features"), ("相关知识", "related")),
    ),
    "entity": PageSchema(
        "entity",
        ("title", "description", "entity_type"),
        (("简介", "description"), ("关键属性", "attributes"), ("关系", "related")),
    ),
    "question": PageSchema(
        "question",
        ("title", "question", "answer"),
        (("问题", "question"), ("答案", "answer"), ("依据", "sources")),
    ),
    "procedure": PageSchema(
        "procedure",
        ("title", "description", "steps"),
        (
            ("目标", "description"),
            ("前置条件", "prerequisites"),
            ("操作步骤", "steps"),
            ("风险", "risks"),
        ),
    ),
    "policy": PageSchema(
        "policy",
        ("title", "description", "rules"),
        (("适用范围", "scope"), ("规则", "rules"), ("例外", "exceptions")),
    ),
    "case": PageSchema(
        "case",
        ("title", "description", "outcome"),
        (("背景", "description"), ("过程", "process"), ("结果", "outcome"), ("经验", "lessons")),
    ),
    "metric": PageSchema(
        "metric",
        ("title", "description", "formula"),
        (("定义", "description"), ("计算口径", "formula"), ("数据来源", "sources")),
    ),
    "term": PageSchema(
        "term",
        ("title", "definition"),
        (("定义", "definition"), ("别名", "aliases"), ("相关术语", "related")),
    ),
}


class SchemaManager:
    """生成和校验受约束的知识页面。"""

    def __init__(self, schemas: dict[str, PageSchema] | None = None) -> None:
        self.schemas = dict(schemas or DEFAULT_SCHEMAS)

    def get_schema(self, page_type: str) -> PageSchema:
        try:
            return self.schemas[page_type]
        except KeyError as exc:
            raise ValueError(f"unsupported_knowledge_page_type:{page_type}") from exc

    def validate(self, page_type: str, data: dict[str, Any]) -> list[str]:
        schema = self.get_schema(page_type)
        return [
            f"missing_required_field:{field}"
            for field in schema.required_fields
            if data.get(field) in (None, "", [], {})
        ]

    def compiler_rule_schema(self) -> dict[str, Any]:
        return {
            "required_page_fields": ["title", "content", "page_type"],
            "required_claim_fields": ["text", "evidence_chunk_id"],
            "required_relation_fields": [
                "source_page_id",
                "target_page_id",
                "relation_type",
            ],
            "allowed_page_types": sorted(self.schemas),
        }

    def generate_page(self, page_type: str, data: dict[str, Any]) -> str:
        errors = self.validate(page_type, data)
        if errors:
            raise ValueError(";".join(errors))

        title = str(data["title"]).strip()
        now = datetime.now(UTC).isoformat()
        frontmatter = {
            "type": page_type,
            "title": title,
            "aliases": list(data.get("aliases") or []),
            "tags": list(data.get("tags") or ["knowledge", page_type]),
            "status": str(data.get("status") or "draft"),
            "authority": str(data.get("authority") or "contextual"),
            "confidence": float(data.get("confidence", 0.5)),
            "source_docs": list(data.get("source_docs") or []),
            "created": str(data.get("created") or now),
            "updated": str(data.get("updated") or now),
            "stale": bool(data.get("stale", False)),
            "managed_by": "opentrace",
        }
        lines = [
            "---",
            yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip(),
            "---",
            "",
            f"# {title}",
        ]
        schema = self.get_schema(page_type)
        for heading, field in schema.sections:
            value = data.get(field)
            if value in (None, "", [], {}):
                continue
            lines.extend(["", f"## {heading}", "", self._render_value(value)])
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _render_value(value: Any) -> str:
        if isinstance(value, dict):
            return "\n".join(f"- **{key}**: {item}" for key, item in value.items())
        if isinstance(value, list | tuple | set):
            return "\n".join(f"- {item}" for item in value)
        return str(value)
