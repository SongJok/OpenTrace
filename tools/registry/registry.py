"""
Tool Registry — central catalog of all available tools.
Uses BM25-style scoring for intent matching.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ToolSpec:
    name: str
    description: str
    fn: Callable[..., Awaitable[Any]]
    tags: list[str] = field(default_factory=list)
    score: float = 1.0
    param_names: list[str] = field(default_factory=list)  # accepted kwargs


class ToolRegistry:
    """Thread-safe in-process tool registry with BM25-style intent matching."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec
        logger.info("Tool registered", name=spec.name, tags=spec.tags)

    def tool(
        self,
        name: str,
        description: str,
        tags: list[str] | None = None,
        param_names: list[str] | None = None,
    ):
        """Decorator to register an async function as a tool."""
        def decorator(fn: Callable):
            import inspect
            # Auto-detect accepted param names from function signature
            sig_params = list(inspect.signature(fn).parameters.keys())
            self.register(ToolSpec(
                name=name,
                description=description,
                fn=fn,
                tags=tags or [],
                param_names=param_names or sig_params,
            ))
            return fn
        return decorator

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def match(self, query: str, top_k: int = 5) -> list[ToolSpec]:
        """
        BM25-inspired intent matching.
        Scores each tool by term overlap against name + description + tags.
        Returns up to top_k results sorted by score descending.
        """
        import math
        tokens = set(_tokenize(query))
        if not tokens:
            return []

        results: list[ToolSpec] = []
        for spec in self._tools.values():
            doc_tokens = _tokenize(
                f"{spec.name} {spec.description} {' '.join(spec.tags)}"
            )
            if not doc_tokens:
                continue

            # TF component
            tf = sum(doc_tokens.count(t) for t in tokens)
            # IDF approximation: boost exact name/tag matches
            name_bonus = 3.0 if any(t in spec.name.lower() for t in tokens) else 0.0
            tag_bonus = sum(
                1.5 for tag in spec.tags
                if any(t in tag.lower() for t in tokens)
            )
            raw_score = tf + name_bonus + tag_bonus

            if raw_score > 0:
                results.append(ToolSpec(
                    name=spec.name,
                    description=spec.description,
                    fn=spec.fn,
                    tags=spec.tags,
                    score=raw_score,
                    param_names=spec.param_names,
                ))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def list_all(self) -> list[str]:
        return list(self._tools.keys())


def _tokenize(text: str) -> list[str]:
    import re

    lowered = text.lower()
    # Keep both latin tokens and CJK chunks so Chinese intents can match tags/descriptions.
    tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", lowered)
    out: list[str] = []
    for tok in tokens:
        out.append(tok)
        # add char-level fallback for CJK chunks to improve partial matching
        if re.fullmatch(r"[\u4e00-\u9fff]+", tok) and len(tok) > 1:
            out.extend(list(tok))
    return out


# Module-level singleton
registry = ToolRegistry()


# Auto-register into the unified CapabilityRegistry when tools are registered
def _auto_register_to_capability(spec: ToolSpec) -> None:
    try:
        from kernel.runtime.capability import capability_registry as cap_reg

        cap_reg.register_tool(spec)
    except ImportError:
        pass


# Monkey-patch register to also feed CapabilityRegistry
_original_register = ToolRegistry.register


def _patched_register(self: ToolRegistry, spec: ToolSpec) -> None:
    _original_register(self, spec)
    _auto_register_to_capability(spec)


ToolRegistry.register = _patched_register  # type: ignore[method-assign]
