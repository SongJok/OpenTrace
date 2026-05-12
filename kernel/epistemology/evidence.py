"""证据层级与标注模型。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvidenceLevel(Enum):
    FACT = 1
    DOCUMENT = 2
    SEARCH = 3
    MEMORY = 4
    INFERENCE = 5
    SPECULATION = 6


class SourceType(Enum):
    DATABASE = "database"
    DOCUMENT = "document"
    WEB_SEARCH = "web_search"
    USER_MEMORY = "user_memory"
    TOOL_OUTPUT = "tool_output"
    MODEL_INFERENCE = "model_inference"
    HYBRID = "hybrid"


@dataclass
class Citation:
    id: str
    source_type: SourceType
    source_name: str
    content_snippet: str
    url: str | None = None


@dataclass
class EvidenceAnnotation:
    level: EvidenceLevel
    source_type: SourceType
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.0
    caveats: list[str] = field(default_factory=list)


@dataclass
class AnnotatedContent:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    text: str = ""
    annotation: EvidenceAnnotation | None = None
    render_hint: dict[str, Any] | None = None

    def to_text(self) -> str:
        if not self.annotation:
            return self.text
        prefix = {
            EvidenceLevel.FACT: "📊",
            EvidenceLevel.DOCUMENT: "📄",
            EvidenceLevel.SEARCH: "🔗",
            EvidenceLevel.MEMORY: "🧠",
            EvidenceLevel.INFERENCE: "💡",
            EvidenceLevel.SPECULATION: "⚠️",
        }.get(self.annotation.level, "ℹ️")
        return f"{prefix} {self.text}"


@dataclass
class AnnotatedResponse:
    fragments: list[AnnotatedContent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_text(self) -> str:
        body = "\n\n".join(f.to_text() for f in self.fragments)
        cites: list[Citation] = []
        for f in self.fragments:
            if f.annotation:
                cites.extend(f.annotation.citations)
        if cites:
            body += "\n\n---\n引用来源"
            for i, c in enumerate(cites, start=1):
                body += f"\n[{i}] {c.source_name}: {c.content_snippet[:120]}"
        return body.strip()
