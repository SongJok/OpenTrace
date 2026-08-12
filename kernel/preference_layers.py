"""桩：用户偏好记忆层分类。"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


class PreferenceLayer(str, enum.Enum):
    EXPLICIT = "explicit"
    BEHAVIORAL = "behavioral"
    WORKSPACE = "workspace"
    SESSION = "session"


@dataclass
class LayeredMemory:
    content: str = ""
    layer: PreferenceLayer = PreferenceLayer.SESSION
    tags: list[str] = field(default_factory=list)


def classify_memories(rows: list[Any], session_id: str = "") -> list[LayeredMemory]:
    results: list[LayeredMemory] = []
    for row in rows:
        kind = getattr(row, "kind", "fact")
        content = getattr(row, "content", "") or ""
        tags = getattr(row, "tags", []) or []
        if kind == "preference":
            layer = PreferenceLayer.EXPLICIT
        elif kind == "workspace_fact":
            layer = PreferenceLayer.WORKSPACE
        elif kind == "session_fact":
            layer = PreferenceLayer.SESSION
        else:
            layer = PreferenceLayer.SESSION
        results.append(LayeredMemory(content=content, layer=layer, tags=tags))
    return results


def build_layered_context_block(layered: list[LayeredMemory]) -> str:
    blocks: list[str] = []
    for lm in layered:
        blocks.append(f"[{lm.layer.value}] {lm.content}")
    return "\n".join(blocks)
