"""
Artifact — 认知回合中产生的命名、版本化数据产品。

示例：生成的图表、SQL 查询结果集、报告文件。
ArtifactManager 负责创建、标签、搜索和存储。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Artifact:
    """认知回合中产生的命名、有类型的数据产品。"""

    artifact_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    turn_id: str = ""
    name: str = ""
    artifact_type: str = "text"  # text | table | chart | code | file
    content: str = ""
    content_type: str = "text/plain"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "name": self.name,
            "artifact_type": self.artifact_type,
            "content": self.content[:500],  # 序列化摘要
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

    def to_runtime_object(self) -> "RuntimeObject":
        """桥接 Artifact → RuntimeObject，用于证据管线。"""
        from kernel.runtime.objects import ObjectType, RuntimeObject

        return RuntimeObject(
            object_id=self.artifact_id,
            object_type=ObjectType.ARTIFACT,
            session_id=self.session_id,
            created_at=self.created_at,
            tags=self.tags,
            metadata={
                "name": self.name,
                "artifact_type": self.artifact_type,
                "content_type": self.content_type,
                "turn_id": self.turn_id,
                **self.metadata,
            },
        )


class ArtifactManager:
    """跨会话管理 artifact。"""

    def __init__(self) -> None:
        self._artifacts: dict[str, Artifact] = {}
        self._by_session: dict[str, list[str]] = {}  # session_id → [artifact_id]

    def create(
        self,
        session_id: str,
        name: str,
        content: str,
        artifact_type: str = "text",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        turn_id: str = "",
    ) -> Artifact:
        artifact = Artifact(
            session_id=session_id,
            turn_id=turn_id or str(uuid.uuid4()),
            name=name,
            artifact_type=artifact_type,
            content=content,
            tags=tags or [],
            metadata=metadata or {},
        )
        self._artifacts[artifact.artifact_id] = artifact
        self._by_session.setdefault(session_id, []).append(artifact.artifact_id)
        logger.debug("Artifact created", id=artifact.artifact_id, name=name)
        return artifact

    def get(self, artifact_id: str) -> Artifact | None:
        return self._artifacts.get(artifact_id)

    def list_by_session(self, session_id: str) -> list[Artifact]:
        ids = self._by_session.get(session_id, [])
        return [self._artifacts[aid] for aid in ids if aid in self._artifacts]

    def search(self, tag: str) -> list[Artifact]:
        return [a for a in self._artifacts.values() if tag in a.tags]
