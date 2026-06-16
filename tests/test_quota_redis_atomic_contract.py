"""Redis-backed quota — atomic reserve (multi-replica)."""

from __future__ import annotations

import pytest
from types import SimpleNamespace


@pytest.fixture
def fake_quota_redis(monkeypatch):
    kv: dict[str, str] = {}
    hashes: dict[str, dict[str, str]] = {}

    class FakeRedis:
        async def get(self, key):
            return kv.get(key)

        async def hgetall(self, key):
            return dict(hashes.get(key, {}))

        async def hset(self, key, field=None, value=None, mapping=None):
            hashes.setdefault(key, {})
            if mapping:
                hashes[key].update({str(k): str(v) for k, v in mapping.items()})
            elif field is not None:
                hashes[key][str(field)] = str(value)

        async def incr(self, key):
            n = int(kv.get(key, "0")) + 1
            kv[key] = str(n)
            return n

        async def incrbyfloat(self, key, amount):
            n = float(kv.get(key, "0")) + float(amount)
            kv[key] = str(n)
            return n

        async def expire(self, key, ttl):
            return True

        async def eval(self, script, numkeys, *args):
            tk, ck, lk = args[0], args[1], args[2]
            est = float(args[3])
            max_turns = int(float(args[4]))
            max_cost = float(args[5])
            turns = int(kv.get(tk, "0"))
            cost = float(kv.get(ck, "0"))
            if turns >= max_turns:
                return [0, "quota_daily_turns_exceeded", turns, cost]
            if cost + est > max_cost:
                return [0, "quota_daily_cost_exceeded", turns, cost]
            turns = await self.incr(tk)
            cost = await self.incrbyfloat(ck, est)
            await self.expire(tk, 172800)
            await self.expire(ck, 172800)
            return [1, "", turns, cost]

    async def fake_cache():
        return FakeRedis()

    monkeypatch.setattr(
        "infra.config.settings.settings",
        SimpleNamespace(enterprise_quota_redis_enabled=True),
    )
    monkeypatch.setattr("infra.cache.redis_client.get_cache_redis", fake_cache)
    return kv


@pytest.mark.asyncio
async def test_reserve_turn_quota_atomic(fake_quota_redis):
    from tenant.quota_redis_store import reserve_turn_quota, turns_key

    key = "tenant:atomic"
    ok, viol, turns, cost = await reserve_turn_quota(
        key, estimated_cost=0.5, max_turns=2, max_cost=10.0
    )
    assert ok is True
    assert viol == []
    assert turns == 1
    assert cost == 0.5

    ok2, _, turns2, _ = await reserve_turn_quota(
        key, estimated_cost=0.1, max_turns=2, max_cost=10.0
    )
    assert ok2 is True
    assert turns2 == 2

    ok3, viol3, _, _ = await reserve_turn_quota(
        key, estimated_cost=0.0, max_turns=2, max_cost=10.0
    )
    assert ok3 is False
    assert "quota_daily_turns_exceeded" in viol3
    assert turns_key(key) in fake_quota_redis


@pytest.mark.asyncio
async def test_quota_manager_consume_async_uses_redis(fake_quota_redis):
    from tenant.quota_manager import QuotaManager
    from tenant.tenant_context import resolve_tenant_context

    ctx = resolve_tenant_context(tenant_id="t-redis", org_id="o", workspace_id="w")
    qm = QuotaManager()
    qm.set_limits(ctx.isolation_key(), daily_turns=1, daily_cost=5.0)

    d1 = await qm.consume_async(ctx, cost=0.2)
    assert d1.allowed is True
    assert d1.turns_used == 1

    d2 = await qm.consume_async(ctx, cost=0.1)
    assert d2.allowed is False
    assert "quota_daily_turns_exceeded" in d2.violations