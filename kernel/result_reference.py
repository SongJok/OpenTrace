"""结果引用类型 — 跨 Agent 数据共享。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResultRef:
    ref_id: str = ""
    type: str = ""
    title: str = ""
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    source_agent: str = ""
    message_id: str = ""


def serialize_refs(refs: list[ResultRef]) -> list[dict[str, Any]]:
    return [
        {
            "ref_id": r.ref_id,
            "type": r.type,
            "title": r.title,
            "summary": r.summary,
            "payload": r.payload,
            "source_agent": r.source_agent,
            "message_id": r.message_id,
        }
        for r in refs
    ]
