"""Reference resolver stub — detects corrections and index/type references."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReferenceResult:
    is_correction: bool = False
    corrected_query: str = ""
    references: list[dict] = field(default_factory=list)


class ReferenceResolver:

    async def resolve_with_llm(
        self,
        query: str,
        conversation_state: Any = None,
        result_refs: Any = None,
    ) -> ReferenceResult:
        return ReferenceResult()
