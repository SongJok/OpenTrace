"""DataAgent 证据保留期维护任务。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import delete

from infra.config.settings import settings
from infra.observability.logger import get_logger
from infra.storage.data_agent_models import DataAgentResultArtifact
from infra.storage.database import AsyncSessionLocal

logger = get_logger(__name__)


async def purge_expired_result_artifacts() -> int:
    """删除超过企业默认保留期的 R1 证据，运行摘要中的哈希仍保留。"""

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(DataAgentResultArtifact).where(
                DataAgentResultArtifact.expires_at.is_not(None),
                DataAgentResultArtifact.expires_at <= datetime.now(UTC),
            )
        )
        await db.commit()
        return int(result.rowcount or 0)


async def data_agent_evidence_maintenance_loop() -> None:
    while True:
        try:
            deleted = await purge_expired_result_artifacts()
            if deleted:
                logger.info("data_agent_result_artifacts_purged", count=deleted)
        except Exception as exc:  # noqa: BLE001 - 周期维护失败不能终止 Worker
            logger.warning("data_agent_result_artifact_purge_failed", error=str(exc))
        await asyncio.sleep(max(60, int(settings.data_deletion_poll_seconds)))
