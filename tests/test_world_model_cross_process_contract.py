"""World Model cross-process facade — noop P0 contracts."""

from __future__ import annotations

import pytest

from world.cross_process_world import (
    CrossProcessBackend,
    get_cross_process_world,
)


@pytest.fixture(autouse=True)
async def _reset_facade():
    await get_cross_process_world().reset_session("cp-s1")
    yield
    await get_cross_process_world().reset_session("cp-s1")


@pytest.mark.asyncio
async def test_publish_and_fetch_merged_lww_in_process():
    wm = get_cross_process_world()
    await wm.publish_slice("cp-s1", "goal", {"root_goal_id": "g1"}, writer_id="pod-a")
    await wm.publish_slice("cp-s1", "goal", {"root_goal_id": "g2"}, writer_id="pod-b")
    snap = await wm.fetch_merged("cp-s1")
    assert snap.session_id == "cp-s1"
    assert snap.slices["goal"]["root_goal_id"] == "g2"
    assert snap.backend == CrossProcessBackend.NOOP.value
    assert snap.merge_policy == "lww_version"


@pytest.mark.asyncio
async def test_multiple_slice_types():
    wm = get_cross_process_world()
    await wm.publish_slice("cp-s1", "capability", {"active": ["data_query"]})
    await wm.publish_slice("cp-s1", "execution", {"phase": "verified"})
    snap = await wm.fetch_merged("cp-s1")
    assert "capability" in snap.slices
    assert "execution" in snap.slices


@pytest.mark.asyncio
async def test_redis_publish_fetch_with_mock_redis(monkeypatch):
    from types import SimpleNamespace

    store: dict[str, dict[str, str]] = {}

    class FakeRedis:
        async def hget(self, key, field):
            return store.get(key, {}).get(field)

        async def hset(self, key, field=None, value=None, mapping=None):
            store.setdefault(key, {})
            if mapping:
                store[key].update(mapping)
            elif field is not None and value is not None:
                store[key][field] = value

        async def hgetall(self, key):
            return dict(store.get(key, {}))

        async def expire(self, key, ttl):
            return True

        async def delete(self, key):
            store.pop(key, None)

    async def fake_get_memory_redis():
        return FakeRedis()

    monkeypatch.setattr(
        "infra.config.settings.settings",
        SimpleNamespace(
            kernel_world_model_cross_process_enabled=True,
            kernel_world_model_cross_process_backend="redis",
        ),
    )
    monkeypatch.setattr(
        "world.cross_process_world_redis._get_redis",
        fake_get_memory_redis,
    )

    wm = get_cross_process_world()
    await wm.reset_session("redis-s1")
    await wm.publish_slice("redis-s1", "execution", {"phase": "verified"}, writer_id="worker-1")
    snap = await wm.fetch_merged("redis-s1")
    assert snap.backend == "redis"
    assert snap.slices["execution"]["phase"] == "verified"


def test_design_doc_exists():
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "docs" / "architecture" / "world_model_cross_process.md"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "WorldSliceEnvelope" in text
    assert "kernel_world_model_cross_process_enabled" in text