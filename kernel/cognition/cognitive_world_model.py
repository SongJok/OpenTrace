"""
Cognitive World Model — unified grounding facade over entity + time lexicon.

Blueprint: single entry for user/environment/tool/data/time relationships at cognition layer.
Does not execute tools.
"""

from __future__ import annotations

from typing import Any

from kernel.cognition.world_model import WorldModel
from kernel.cognition.entity_registry import EntityRecord

class CognitiveWorldModel:
    """Facade: ground terms, register entities, batch ground queries."""

    def __init__(self) -> None:
        self._wm = WorldModel()

    def ground(self, term: str):
        return self._wm.ground(term)

    def ground_query(self, query: str):
        return self._wm.ground_query(query)

    def register_entity(
        self,
        canonical_name: str,
        entity_type: str,
        aliases: list[str] | None = None,
        mappings: dict[str, Any] | None = None,
    ) -> None:
        self._wm.entity_registry.register(
            EntityRecord(
                canonical_name=canonical_name,
                entity_type=entity_type,
                aliases=aliases or [],
                mappings=mappings or {},
            )
        )

    @property
    def entity_registry(self):
        return self._wm.entity_registry

def get_cognitive_world_model() -> CognitiveWorldModel:
    if not hasattr(get_cognitive_world_model, "_inst"):
        get_cognitive_world_model._inst = CognitiveWorldModel()  # type: ignore[attr-defined]
    return get_cognitive_world_model._inst  # type: ignore[attr-defined]