"""Cross-process World Model facade — noop backend until P1 Redis (see docs/architecture/world_model_cross_process.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)

WorldSliceType = str  # goal | capability | risk | temporal | execution


class CrossProcessBackend(str, Enum):
    NOOP = "noop"
    REDIS = "redis"


@dataclass
class WorldSliceEnvelope:
    session_id: str = ""
    slice_type: WorldSliceType = "goal"
    payload: dict[str, Any] = field(default_factory=dict)
    version: int = 0
    writer_id: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "slice_type": self.slice_type,
            "payload": dict(self.payload),
            "version": self.version,
            "writer_id": self.writer_id,
            "updated_at": self.updated_at,
        }


@dataclass
class MergedWorldSnapshot:
    session_id: str = ""
    slices: dict[str, dict[str, Any]] = field(default_factory=dict)
    merge_policy: str = "lww_version"
    stale: bool = False
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    backend: str = "noop"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "slices": dict(self.slices),
            "merge_policy": self.merge_policy,
            "stale": self.stale,
            "conflicts": list(self.conflicts),
            "backend": self.backend,
        }


def _backend_name() -> CrossProcessBackend:
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_world_model_cross_process_enabled", False)):
            return CrossProcessBackend.NOOP
        raw = str(getattr(settings, "kernel_world_model_cross_process_backend", "noop") or "noop").lower()
        if raw == "redis":
            return CrossProcessBackend.REDIS
    except Exception as exc:
        logger.debug("cross_process_backend_read_skipped", error=str(exc))
    return CrossProcessBackend.NOOP


class CrossProcessWorldFacade:
    """Publish/fetch world slices across replicas (noop stores in-process only)."""

    def __init__(self) -> None:
        self._local: dict[str, dict[str, WorldSliceEnvelope]] = {}

    async def publish_slice(
        self,
        session_id: str,
        slice_type: WorldSliceType,
        payload: dict[str, Any],
        *,
        writer_id: str = "api",
    ) -> WorldSliceEnvelope:
        backend = _backend_name()
        sid = session_id or "default"
        per_session = self._local.setdefault(sid, {})
        prev = per_session.get(slice_type)

        if backend == CrossProcessBackend.REDIS:
            try:
                from world.cross_process_world_redis import redis_publish_slice

                env = await redis_publish_slice(
                    sid,
                    slice_type,
                    payload,
                    writer_id=writer_id,
                    local_prev=prev,
                )
                per_session[slice_type] = env
                return env
            except Exception as exc:
                logger.warning(
                    "cross_process_redis_publish_fallback_local",
                    session_id=sid,
                    error=str(exc),
                )

        version = (prev.version + 1) if prev else 1
        env = WorldSliceEnvelope(
            session_id=sid,
            slice_type=slice_type,
            payload=dict(payload),
            version=version,
            writer_id=writer_id,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        per_session[slice_type] = env
        return env

    async def fetch_merged(self, session_id: str) -> MergedWorldSnapshot:
        backend = _backend_name()
        sid = session_id or "default"

        if backend == CrossProcessBackend.REDIS:
            try:
                from world.cross_process_world_redis import (
                    bridge_execution_slice_to_grounding,
                    redis_fetch_merged,
                )

                snap = await redis_fetch_merged(sid)
                bridge_execution_slice_to_grounding(sid, snap)
                return snap
            except Exception as exc:
                logger.warning(
                    "cross_process_redis_fetch_fallback_local",
                    session_id=sid,
                    error=str(exc),
                )

        per_session = self._local.get(sid, {})
        slices = {k: dict(v.payload) for k, v in per_session.items()}
        return MergedWorldSnapshot(
            session_id=sid,
            slices=slices,
            backend=backend.value,
        )

    async def reset_session(self, session_id: str) -> None:
        sid = session_id or "default"
        self._local.pop(sid, None)
        if _backend_name() == CrossProcessBackend.REDIS:
            try:
                from world.cross_process_world_redis import redis_reset_session

                await redis_reset_session(sid)
            except Exception as exc:
                logger.debug("cross_process_redis_reset_skipped", error=str(exc))


_facade: CrossProcessWorldFacade | None = None


def get_cross_process_world() -> CrossProcessWorldFacade:
    global _facade
    if _facade is None:
        _facade = CrossProcessWorldFacade()
    return _facade