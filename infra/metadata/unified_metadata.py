"""
UnifiedMetadata — 所有数据必须携带的统一元数据

规则：所有 Memory / Document / Tool / Web 数据必须带此元数据。
用于：统一检索排序、权限过滤、多源融合、版本管理。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class UnifiedMetadata:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = "memory"           # memory | document | tool | web | knowledge
    source: str = "system"         # upload | web | system | user
    owner: str = ""                # user_id
    tenant: str = "default"        # tenant_id (多租户)
    tags: list[str] = field(default_factory=list)
    embedding_id: str = ""         # 对应向量 ID
    timestamp: int = field(default_factory=lambda: int(time.time()))
    confidence: float = 1.0        # 0.0 - 1.0
    permissions: dict[str, Any] = field(default_factory=lambda: {"read": [], "write": []})
    version: int = 1
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "source": self.source,
            "owner": self.owner,
            "tenant": self.tenant,
            "tags": self.tags,
            "embedding_id": self.embedding_id,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "permissions": self.permissions,
            "version": self.version,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UnifiedMetadata":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def can_read(self, user_id: str) -> bool:
        """权限检查：用户是否有读权限。"""
        if self.owner == user_id:
            return True
        readers = self.permissions.get("read", [])
        return "*" in readers or user_id in readers

    def can_write(self, user_id: str) -> bool:
        """权限检查：用户是否有写权限。"""
        if self.owner == user_id:
            return True
        writers = self.permissions.get("write", [])
        return "*" in writers or user_id in writers


def make_doc_metadata(owner: str, tags: Optional[list[str]] = None) -> UnifiedMetadata:
    return UnifiedMetadata(
        type="document",
        source="upload",
        owner=owner,
        tags=tags or [],
        permissions={"read": [owner], "write": [owner]},
    )


def make_memory_metadata(owner: str, session_id: str = "") -> UnifiedMetadata:
    return UnifiedMetadata(
        type="memory",
        source="system",
        owner=owner,
        extra={"session_id": session_id},
        permissions={"read": [owner], "write": [owner]},
    )


def make_web_metadata(url: str = "") -> UnifiedMetadata:
    return UnifiedMetadata(
        type="web",
        source="web",
        confidence=0.7,
        extra={"url": url},
        permissions={"read": ["*"]},
    )
