"""
Audit Logger — records security-relevant events to a tamper-evident log.
"""
from __future__ import annotations

import json
import time
from enum import Enum
from typing import Any, Optional

from infra.cache.redis_client import get_queue_redis
from infra.observability.logger import get_logger

logger = get_logger(__name__)

AUDIT_KEY = "opentrace:audit:log"
AUDIT_TTL = 30 * 24 * 3600  # 30 days


class AuditEventType(str, Enum):
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILURE = "auth_failure"
    GUARDRAIL_BLOCK = "guardrail_block"
    TOOL_EXECUTION = "tool_execution"
    AGENT_START = "agent_start"
    AGENT_COMPLETE = "agent_complete"
    DATA_ACCESS = "data_access"


class AuditLogger:
    async def log(
        self,
        event_type: AuditEventType,
        user_id: str = "",
        session_id: str = "",
        detail: Optional[dict[str, Any]] = None,
    ) -> None:
        r = await get_queue_redis()
        entry = json.dumps({
            "event": event_type.value,
            "user_id": user_id,
            "session_id": session_id,
            "detail": detail or {},
            "ts": time.time(),
        })
        await r.rpush(AUDIT_KEY, entry)
        await r.expire(AUDIT_KEY, AUDIT_TTL)
        logger.info(
            "Audit event",
            event=event_type.value,
            user=user_id,
            session=session_id,
        )


audit_logger = AuditLogger()
