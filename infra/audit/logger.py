from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from infra.storage.database import AsyncSessionLocal
from infra.storage.models import AuditLog


def _mask_payload(data: dict[str, Any]) -> dict[str, Any]:
    masked: dict[str, Any] = {}
    for k, v in (data or {}).items():
        lk = k.lower()
        if any(x in lk for x in ["token", "password", "secret", "key", "authorization"]):
            masked[k] = "***"
        else:
            masked[k] = v
    return masked


async def write_audit_log(user_id: str, action: str, resource_type: str, resource_id: str, payload: dict[str, Any] | None = None) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            AuditLog(
                id=str(uuid.uuid4()),
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                payload_json=json.dumps(_mask_payload(payload or {}), ensure_ascii=False),
                created_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
