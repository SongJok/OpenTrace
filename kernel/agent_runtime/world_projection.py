"""World Projection Layer — current / projected / counterfactual slices for decision loop."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from infra.observability.logger import get_logger

logger = get_logger(__name__)

ProjectionKind = Literal["current", "projected", "counterfactual"]


class WorldProjection(BaseModel):
    kind: ProjectionKind = "current"
    session_id: str = ""
    tenant_id: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    source: str = "world_runtime"
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldProjectionBundle(BaseModel):
    """Bundle attached to RuntimeContext.metadata for planners / data runtime."""

    current: WorldProjection | None = None
    projected: WorldProjection | None = None
    counterfactual: WorldProjection | None = None
    version: str = "world_projection_v1"

    def to_metadata_dict(self) -> dict[str, Any]:
        return {
            "world_projection": self.model_dump(mode="json"),
            "world_projection_version": self.version,
        }


def build_projection_bundle_from_context(ctx: Any) -> WorldProjectionBundle:
    md = dict(getattr(ctx, "metadata", None) or {})
    session_id = str(getattr(ctx, "session_id", "") or "")
    tenant_id = str(md.get("tenant_id") or md.get("x_tenant_id") or "")
    existing = md.get("world_projection")
    if isinstance(existing, dict) and existing.get("current"):
        try:
            return WorldProjectionBundle.model_validate(existing)
        except Exception as exc:
            logger.debug("world_projection_validate_skipped", error=str(exc))

    ws = md.get("world_state") or md.get("world_snapshot") or {}
    variables = dict(ws) if isinstance(ws, dict) else {}
    current = WorldProjection(
        kind="current",
        session_id=session_id,
        tenant_id=tenant_id,
        variables=variables,
        confidence=0.7 if variables else 0.3,
    )
    return WorldProjectionBundle(current=current)


def apply_counterfactual_assumption(
    bundle: WorldProjectionBundle,
    *,
    assumption: str,
    variable_deltas: dict[str, Any],
) -> WorldProjectionBundle:
    base_vars = dict((bundle.current.variables if bundle.current else {}) or {})
    for k, v in variable_deltas.items():
        if isinstance(v, dict) and v.get("op") == "scale" and k in base_vars:
            try:
                base_vars[k] = float(base_vars[k]) * float(v.get("factor", 1.0))
            except (TypeError, ValueError):
                base_vars[k] = v
        else:
            base_vars[k] = v
    cf = WorldProjection(
        kind="counterfactual",
        session_id=bundle.current.session_id if bundle.current else "",
        tenant_id=bundle.current.tenant_id if bundle.current else "",
        variables=base_vars,
        assumptions=[assumption],
        confidence=0.55,
        metadata={"derived_from": "counterfactual_engine"},
    )
    return bundle.model_copy(update={"counterfactual": cf})