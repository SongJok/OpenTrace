"""前端渲染提示（占位原型）。"""

from __future__ import annotations

from kernel.epistemology.evidence import AnnotatedContent, EvidenceLevel


def build_render_hint(content: AnnotatedContent) -> dict:
    if not content.annotation:
        return {"type": "plain"}
    level = content.annotation.level
    if level == EvidenceLevel.FACT:
        return {"type": "data_card", "highlight": "strong"}
    if level == EvidenceLevel.DOCUMENT:
        return {"type": "citation_block"}
    if level == EvidenceLevel.SEARCH:
        return {"type": "external_link"}
    if level == EvidenceLevel.INFERENCE:
        return {"type": "inference", "italic": True}
    if level == EvidenceLevel.SPECULATION:
        return {"type": "warning", "muted": True}
    return {"type": "plain"}
