#!/usr/bin/env python3
"""将 PostgreSQL Base64 附件幂等迁移到配置的对象存储。"""

from __future__ import annotations

import argparse
import asyncio
import base64

from sqlalchemy import or_, select

from infra.storage.database import AsyncSessionLocal
from infra.storage.models import Attachment
from infra.storage.object_store import attachment_object_key, get_object_store


async def migrate(*, batch_size: int, apply: bool) -> dict[str, int]:
    store = get_object_store()
    if store is None:
        raise RuntimeError("OBJECT_STORAGE_BACKEND 必须为 local 或 s3")
    scanned = migrated = 0
    while True:
        async with AsyncSessionLocal() as db:
            rows = list(
                (
                    await db.scalars(
                        select(Attachment)
                        .where(
                            Attachment.object_key.is_(None),
                            or_(
                                Attachment.image_base64.is_not(None),
                                Attachment.media_base64.is_not(None),
                            ),
                        )
                        .order_by(Attachment.id)
                        .limit(batch_size)
                    )
                ).all()
            )
            if not rows:
                break
            scanned += len(rows)
            if not apply:
                break
            for row in rows:
                encoded = row.image_base64 or row.media_base64 or ""
                raw = base64.b64decode(encoded, validate=True)
                content_hash = row.content_hash or __import__("hashlib").sha256(raw).hexdigest()
                key = attachment_object_key(
                    tenant_id=row.tenant_id,
                    workspace_id=row.workspace_id,
                    content_hash=content_hash,
                )
                ref = await store.put(key, raw, row.mime_type or "application/octet-stream")
                row.storage_backend = ref.backend
                row.object_key = ref.key
                row.object_etag = ref.etag
                row.image_base64 = None
                row.media_base64 = None
                migrated += 1
            await db.commit()
    return {"scanned": scanned, "migrated": migrated, "dry_run": int(not apply)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(asyncio.run(migrate(batch_size=max(1, args.batch_size), apply=args.apply)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
