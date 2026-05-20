"""Stub: Context Assembler — V5 feature not yet implemented."""

from __future__ import annotations

from dataclasses import dataclass, field

from infra.observability.logger import get_logger

logger = get_logger(__name__)
_WARNED = False


@dataclass
class StructuredSummary:
    sections: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        return "\n".join(self.sections)


@dataclass
class AssembledContext:
    structured_summary: StructuredSummary = field(default_factory=StructuredSummary)
    compressed: bool = False
    total_tokens: int = 0
    recent_turns: list[dict[str, str]] = field(default_factory=list)
    memory_injection_query: str = ""
    summary_block: str = ""


class ContextAssembler:
    async def assemble(self, tctx) -> AssembledContext:
        global _WARNED
        if not _WARNED:
            logger.warning(
                "ContextAssembler is a stub — V5 context assembler feature not yet implemented"
            )
            _WARNED = True
        return AssembledContext()


_assembler: ContextAssembler | None = None


def get_context_assembler() -> ContextAssembler:
    global _assembler
    if _assembler is None:
        _assembler = ContextAssembler()
    return _assembler
