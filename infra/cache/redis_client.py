from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import redis.asyncio as aioredis

from infra.cache.redis_shadow_store import shadow_store
from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)
_pools: dict[int, aioredis.Redis] = {}
_lock = asyncio.Lock()
_db_limit: Optional[int] = None


class ShadowPipeline:
    def __init__(self, db: int, r: aioredis.Redis):
        self.db, self.r = db, r
        self.p = r.pipeline()
        self.ops: list[tuple[str, tuple[Any, ...]]] = []

    def zremrangebyscore(self, k, lo, hi): self.ops.append(("zrem", (k, lo, hi))); self.p.zremrangebyscore(k, lo, hi); return self
    def zadd(self, k, m): self.ops.append(("zadd", (k, m))); self.p.zadd(k, m); return self
    def zcard(self, k): self.ops.append(("zcard", (k,))); self.p.zcard(k); return self
    def expire(self, k, ttl): self.ops.append(("exp", (k, ttl))); self.p.expire(k, ttl); return self
    def lpop(self, k): self.ops.append(("lpop", (k,))); self.p.lpop(k); return self

    async def execute(self):
        out = await self.p.execute()
        await self._sync()
        return out

    async def _sync(self):
        state: dict[str, tuple[str, Any, Optional[float]]] = {}

        async def load(k: str, t: str):
            if k in state:
                return
            row = await shadow_store.get(self.db, k)
            if row and row[0] == t:
                state[k] = row
            else:
                init = {"members": {}} if t == "zset" else {"items": []}
                state[k] = (t, init, None)

        for op, args in self.ops:
            if op == "zrem":
                k, lo, hi = args; await load(k, "zset")
                t, payload, exp = state[k]
                mem = dict(payload.get("members", {}))
                lo, hi = float(lo), float(hi)
                for m in list(mem):
                    s = float(mem[m])
                    if lo <= s <= hi: mem.pop(m, None)
                state[k] = (t, {"members": mem}, exp)
            elif op == "zadd":
                k, mp = args; await load(k, "zset")
                t, payload, exp = state[k]
                mem = dict(payload.get("members", {})); mem.update({str(m): float(s) for m, s in mp.items()})
                state[k] = (t, {"members": mem}, exp)
            elif op == "exp":
                k, ttl = args
                if k in state:
                    t, payload, _ = state[k]
                    state[k] = (t, payload, time.time() + max(int(ttl), 0))
            elif op == "lpop":
                k = args[0]; await load(k, "list")
                t, payload, exp = state[k]
                items = list(payload.get("items", []))
                if items: items.pop(0)
                state[k] = (t, {"items": items}, exp)

        for k, (t, payload, exp) in state.items():
            await shadow_store.upsert(self.db, k, t, payload, exp)


class ShadowRedis:
    def __init__(self, db: int, r: aioredis.Redis): self.db, self.r = db, r
    def pipeline(self): return ShadowPipeline(self.db, self.r)
    def pubsub(self): return self.r.pubsub()
    async def aclose(self): await self.r.aclose()

    async def set(self, k, v):
        ok = await self.r.set(k, v); await shadow_store.upsert(self.db, k, "string", {"value": v}); return ok

    async def setex(self, k, ttl, v):
        ok = await self.r.set(k, v, ex=ttl); await shadow_store.upsert(self.db, k, "string", {"value": v}, time.time()+max(int(ttl),0)); return ok

    async def get(self, k):
        v = await self.r.get(k)
        if v is not None: return v
        row = await shadow_store.get(self.db, k)
        if not row or row[0] != "string": return None
        v, exp = row[1].get("value"), row[2]
        if v is None: return None
        ttl = int(exp - time.time()) if exp else None
        if ttl and ttl > 0: await self.r.set(k, v, ex=ttl)
        else: await self.r.set(k, v)
        return v

    async def hset(self, k, field=None, value=None, mapping=None):
        if mapping is not None:
            res = await self.r.hset(k, mapping=mapping)
            row = await shadow_store.get(self.db, k)
            fields = dict((row[1].get("fields", {}) if row and row[0]=="hash" else {})); fields.update(mapping)
            await shadow_store.upsert(self.db, k, "hash", {"fields": fields}, row[2] if row else None)
            return res
        res = await self.r.hset(k, field, value)
        row = await shadow_store.get(self.db, k)
        fields = dict((row[1].get("fields", {}) if row and row[0]=="hash" else {})); fields[str(field)] = value
        await shadow_store.upsert(self.db, k, "hash", {"fields": fields}, row[2] if row else None)
        return res

    async def hget(self, k, f):
        v = await self.r.hget(k, f)
        if v is not None: return v
        row = await shadow_store.get(self.db, k)
        if not row or row[0] != "hash": return None
        v = row[1].get("fields", {}).get(str(f))
        if v is not None: await self.r.hset(k, f, v)
        return v

    async def hgetall(self, k):
        m = await self.r.hgetall(k)
        if m: return m
        row = await shadow_store.get(self.db, k)
        if not row or row[0] != "hash": return {}
        m = row[1].get("fields", {})
        if m: await self.r.hset(k, mapping=m)
        return m

    async def delete(self, k):
        res = await self.r.delete(k); await shadow_store.mark_deleted(self.db, k); return res

    async def expire(self, k, ttl):
        res = await self.r.expire(k, ttl); await shadow_store.set_expire(self.db, k, ttl); return res

    async def rpush(self, k, *vals):
        res = await self.r.rpush(k, *vals)
        row = await shadow_store.get(self.db, k); items = list(row[1].get("items", []) if row and row[0]=="list" else [])
        items.extend(vals); await shadow_store.upsert(self.db, k, "list", {"items": items}, row[2] if row else None)
        return res

    async def lrange(self, k, s, e):
        arr = await self.r.lrange(k, s, e)
        if arr: return arr
        row = await shadow_store.get(self.db, k)
        if not row or row[0] != "list": return []
        items = list(row[1].get("items", []))
        if items: await self.r.rpush(k, *items)
        n = len(items); s = s if s >= 0 else n + s; e = e if e >= 0 else n + e
        s, e = max(0, s), min(n - 1, e)
        return items[s:e+1] if n and s <= e else []

    async def lpop(self, k):
        v = await self.r.lpop(k)
        row = await shadow_store.get(self.db, k)
        if not row or row[0] != "list": return v
        items = list(row[1].get("items", []))
        if v is None and items: v = items.pop(0)
        elif v is not None and items: items.pop(0)
        await shadow_store.upsert(self.db, k, "list", {"items": items}, row[2])
        return v

    async def sadd(self, k, *mem):
        res = await self.r.sadd(k, *mem)
        row = await shadow_store.get(self.db, k); s = set(row[1].get("members", []) if row and row[0]=="set" else [])
        s.update(str(x) for x in mem); await shadow_store.upsert(self.db, k, "set", {"members": sorted(s)}, row[2] if row else None)
        return res

    async def srem(self, k, *mem):
        res = await self.r.srem(k, *mem)
        row = await shadow_store.get(self.db, k)
        if row and row[0] == "set":
            s = set(row[1].get("members", [])); [s.discard(str(x)) for x in mem]
            await shadow_store.upsert(self.db, k, "set", {"members": sorted(s)}, row[2])
        return res

    async def smembers(self, k):
        s = await self.r.smembers(k)
        if s: return s
        row = await shadow_store.get(self.db, k)
        if not row or row[0] != "set": return set()
        s = set(row[1].get("members", []))
        if s: await self.r.sadd(k, *list(s))
        return s

    async def zadd(self, k, mapping):
        res = await self.r.zadd(k, mapping)
        row = await shadow_store.get(self.db, k); mem = dict(row[1].get("members", {}) if row and row[0]=="zset" else {})
        mem.update({str(m): float(sc) for m, sc in mapping.items()}); await shadow_store.upsert(self.db, k, "zset", {"members": mem}, row[2] if row else None)
        return res

    async def zremrangebyscore(self, k, lo, hi):
        res = await self.r.zremrangebyscore(k, lo, hi)
        row = await shadow_store.get(self.db, k)
        if row and row[0] == "zset":
            mem = dict(row[1].get("members", {})); lo, hi = float(lo), float(hi)
            for m in list(mem):
                sc = float(mem[m])
                if lo <= sc <= hi: mem.pop(m, None)
            await shadow_store.upsert(self.db, k, "zset", {"members": mem}, row[2])
        return res

    async def zcard(self, k):
        c = await self.r.zcard(k)
        if c: return c
        row = await shadow_store.get(self.db, k)
        if not row or row[0] != "zset": return 0
        mem = dict(row[1].get("members", {}))
        if mem: await self.r.zadd(k, mem)
        return len(mem)

    async def publish(self, ch, payload):
        res = await self.r.publish(ch, payload)
        key = f"opentrace:pubsub:shadow:{ch}"
        row = await shadow_store.get(self.db, key); items = list(row[1].get("items", []) if row and row[0]=="list" else [])
        items.append(payload); items = items[-2000:]
        await shadow_store.upsert(self.db, key, "list", {"items": items}, time.time()+7*24*3600)
        return res

    async def xadd(self, stream, fields, maxlen=None):
        if maxlen is not None:
            return await self.r.xadd(stream, fields, maxlen=maxlen, approximate=True)
        return await self.r.xadd(stream, fields)

    async def xgroup_create(self, stream, groupname, id="0", mkstream=False):
        return await self.r.xgroup_create(stream, groupname, id=id, mkstream=mkstream)

    async def xreadgroup(self, groupname, consumername, streams, count=1, block=1000):
        return await self.r.xreadgroup(groupname, consumername, streams=streams, count=count, block=block)

    async def xack(self, stream, groupname, *ids):
        return await self.r.xack(stream, groupname, *ids)

    async def xpending_range(self, stream, groupname, min='-', max='+', count=10):
        return await self.r.xpending_range(stream, groupname, min=min, max=max, count=count)

    async def xclaim(self, stream, groupname, consumername, min_idle_time, message_ids):
        return await self.r.xclaim(stream, groupname, consumername, min_idle_time=min_idle_time, message_ids=message_ids)


async def _get_db_limit() -> int:
    global _db_limit
    if _db_limit is not None:
        return _db_limit
    base_client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
        health_check_interval=30,
    )
    try:
        cfg = await base_client.config_get("databases")
        raw = cfg.get("databases", "16") if isinstance(cfg, dict) else "16"
        _db_limit = int(raw)
    except Exception:
        _db_limit = 16
    finally:
        await base_client.aclose()
    return _db_limit


def _normalize_db_index(db: int, db_limit: int) -> int:
    if db_limit <= 0:
        return db
    if 0 <= db < db_limit:
        return db
    normalized = db % db_limit
    logger.warning("Redis DB index out of range, remapped", requested=db, normalized=normalized, db_limit=db_limit)
    return normalized


async def get_redis(db: Optional[int] = None) -> ShadowRedis:
    db = settings.redis_session_db if db is None else db
    db_limit = await _get_db_limit()
    db = _normalize_db_index(int(db), db_limit)
    t0 = time.monotonic()
    async with _lock:
        if db not in _pools:
            base = settings.redis_url.rsplit("/", 1)[0]
            url = f"{base}/{db}"
            _pools[db] = aioredis.from_url(url, encoding="utf-8", decode_responses=True, socket_connect_timeout=5, socket_timeout=5, retry_on_timeout=True, health_check_interval=30)
            logger.info("Redis pool created", db=db, url=url, latency_ms=int((time.monotonic() - t0) * 1000))
    return ShadowRedis(db, _pools[db])


async def get_session_redis() -> ShadowRedis: return await get_redis(settings.redis_session_db)
async def get_cache_redis() -> ShadowRedis: return await get_redis(settings.redis_cache_db)
async def get_memory_redis() -> ShadowRedis: return await get_redis(settings.redis_memory_db)
async def get_queue_redis() -> ShadowRedis: return await get_redis(settings.redis_queue_db)
async def get_pubsub_redis() -> ShadowRedis: return await get_redis(settings.redis_pubsub_db)
async def get_rate_limit_redis() -> ShadowRedis: return await get_redis(settings.redis_rate_limit_db)


async def close_all() -> None:
    async with _lock:
        for db, c in _pools.items():
            await c.aclose(); logger.info("Redis pool closed", db=db)
        _pools.clear()
