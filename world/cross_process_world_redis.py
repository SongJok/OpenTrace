"""Redis HASH backend for cross-process world slices (P1)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from infra.observability.logger import get_logger
from world.cross_process_world import MergedWorldSnapshot, WorldSliceEnvelope, WorldSliceType

logger = get_logger(__name__)

_NS = "opentrace:wm:slice"


def _hash_key(session_id: str) -> str:
    return f"{_NS}:{session_id or 'default'}"


def _field(slice_type: WorldSliceType) -> str:
    return str(slice_type)


async def _get_redis():
    from infra.cache.redis_client import get_memory_redis

    return await get_memory_redis()


def envelope_from_json(raw: str) -> WorldSliceEnvelope | None:
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return WorldSliceEnvelope(
            session_id=str(data.get("session_id", "")),
            slice_type=str(data.get("slice_type", "goal")),
            payload=dict(data.get("payload") or {}),
            version=int(data.get("version", 0) or 0),
            writer_id=str(data.get("writer_id", "")),
            updated_at=str(data.get("updated_at", "")),
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.debug("cross_process_envelope_parse_failed", error=str(exc))
        return None


async def redis_publish_slice(
    session_id: str,
    slice_type: WorldSliceType,
    payload: dict[str, Any],
    *,
    writer_id: str = "api",
    local_prev: WorldSliceEnvelope | None = None,
) -> WorldSliceEnvelope:
    sid = session_id or "default"
    r = await _get_redis()
    hk = _hash_key(sid)
    field = _field(slice_type)

    prev = local_prev
    if prev is None:
        raw_prev = await r.hget(hk, field)
        if raw_prev:
            if isinstance(raw_prev, bytes):
                raw_prev = raw_prev.decode("utf-8", errors="replace")
            prev = envelope_from_json(str(raw_prev))

    version = (prev.version + 1) if prev else 1
    env = WorldSliceEnvelope(
        session_id=sid,
        slice_type=slice_type,
        payload=dict(payload),
        version=version,
        writer_id=writer_id,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    await r.hset(hk, field, json.dumps(env.to_dict(), ensure_ascii=False))
    await r.expire(hk, 172800)
    return env


async def redis_fetch_merged(session_id: str) -> MergedWorldSnapshot:
    sid = session_id or "default"
    r = await _get_redis()
    hk = _hash_key(sid)
    data = await r.hgetall(hk)
    slices: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []

    if not data:
        return MergedWorldSnapshot(session_id=sid, slices=slices, backend="redis")

    for key, raw in data.items():
        sk = key.decode("utf-8") if isinstance(key, bytes) else str(key)
        rs = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        env = envelope_from_json(rs)
        if env:
            slices[sk] = dict(env.payload)

    return MergedWorldSnapshot(
        session_id=sid,
        slices=slices,
        backend="redis",
        conflicts=conflicts,
    )


async def redis_reset_session(session_id: str) -> None:
    r = await _get_redis()
    await r.delete(_hash_key(session_id or "default"))


def bridge_execution_slice_to_grounding(session_id: str, snapshot: MergedWorldSnapshot) -> None:
    """Merge execution slice from cross-process snapshot into in-process grounding."""
    exec_payload = snapshot.slices.get("execution")
    if not exec_payload:
        return
    try:
        from kernel.cognition.runtime_grounding import get_grounding

        state = get_grounding(session_id)
        phase = str(exec_payload.get("phase") or state.execution.phase)
        state.execution.phase = phase
    except Exception as exc:
        logger.debug("cross_process_grounding_bridge_skipped", error=str(exc))