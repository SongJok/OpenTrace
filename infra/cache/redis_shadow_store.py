"""
Redis Shadow Store (PostgreSQL)
- Dual-write target for Redis writes
- Fallback source when Redis misses
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from sqlalchemy import select

from infra.observability.logger import get_logger
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import RedisShadowKV

logger = get_logger(__name__)


class RedisShadowStore:
    async def upsert(
        self,
        redis_db: int,
        key: str,
        data_type: str,
        payload: Any,
        expire_at_ts: Optional[float] = None,
    ) -> None:
        try:
            async with AsyncSessionLocal() as db:
                row = await self._get_row(db, redis_db, key)
                payload_json = json.dumps(payload)
                if row is None:
                    row = RedisShadowKV(
                        redis_db=redis_db,
                        redis_key=key,
                        data_type=data_type,
                        payload_json=payload_json,
                        expire_at_ts=expire_at_ts,
                        is_deleted=False,
                    )
                    db.add(row)
                else:
                    row.data_type = data_type
                    row.payload_json = payload_json
                    row.expire_at_ts = expire_at_ts
                    row.is_deleted = False
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Redis shadow upsert failed", key=key, error=str(exc))

    async def get(self, redis_db: int, key: str) -> Optional[tuple[str, Any, Optional[float]]]:
        try:
            async with AsyncSessionLocal() as db:
                row = await self._get_row(db, redis_db, key)
                if row is None or row.is_deleted:
                    return None
                if row.expire_at_ts and row.expire_at_ts <= time.time():
                    return None
                return row.data_type, json.loads(row.payload_json), row.expire_at_ts
        except Exception as exc:  # noqa: BLE001
            logger.debug("Redis shadow get failed", key=key, error=str(exc))
            return None

    async def mark_deleted(self, redis_db: int, key: str) -> None:
        try:
            async with AsyncSessionLocal() as db:
                row = await self._get_row(db, redis_db, key)
                if row is None:
                    return
                row.is_deleted = True
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Redis shadow delete mark failed", key=key, error=str(exc))

    async def set_expire(self, redis_db: int, key: str, ttl_seconds: int) -> None:
        try:
            async with AsyncSessionLocal() as db:
                row = await self._get_row(db, redis_db, key)
                if row is None:
                    return
                row.expire_at_ts = time.time() + max(ttl_seconds, 0)
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Redis shadow expire failed", key=key, error=str(exc))

    async def _get_row(self, db, redis_db: int, key: str) -> Optional[RedisShadowKV]:
        stmt = select(RedisShadowKV).where(
            RedisShadowKV.redis_db == redis_db,
            RedisShadowKV.redis_key == key,
        )
        res = await db.execute(stmt)
        return res.scalars().first()


shadow_store = RedisShadowStore()
