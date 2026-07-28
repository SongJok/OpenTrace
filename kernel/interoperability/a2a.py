"""A2A 消息信封与租户绑定签名。"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class A2AMessage:
    message_id: str
    task_id: str
    sender: str
    recipient: str
    tenant_id: str
    workspace_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def canonical_bytes(self) -> bytes:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode("utf-8")


class A2ASigner:
    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("A2A service identity secret 至少 32 字符")
        self.secret = secret.encode()

    def sign(self, message: A2AMessage) -> str:
        return hmac.new(self.secret, message.canonical_bytes(), hashlib.sha256).hexdigest()

    def verify(self, message: A2AMessage, signature: str) -> bool:
        return hmac.compare_digest(self.sign(message), signature)
