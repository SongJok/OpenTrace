"""与业务事务同提交的生产智能审计记录。"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import AuditLog

_SENSITIVE_MARKERS = ("token", "password", "secret", "api_key", "authorization", "credential")


def mask_sensitive(value: Any, *, key: str = "") -> Any:
    if any(marker in key.lower() for marker in _SENSITIVE_MARKERS):
        return "***"
    if isinstance(value, dict):
        return {str(k): mask_sensitive(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    return value


def append_audit(
    db: AsyncSession,
    *,
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """加入当前事务；调用方负责提交，避免业务与审计出现先后不一致。"""

    db.add(
        AuditLog(
            id=str(uuid.uuid4()),
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            payload_json=json.dumps(mask_sensitive(payload or {}), ensure_ascii=False),
        )
    )
