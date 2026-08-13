"""DataAgent 证据保留期维护任务。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import update

from infra.config.settings import settings
from infra.observability.logger import get_logger
from infra.storage.data_agent_models import DataAgentResultArtifact
from infra.storage.database import AsyncSessionLocal

logger = get_logger(__name__)


async def purge_expired_result_artifacts() -> int:
    """到期后清除可识别明细，但保留 R1 哈希与版本用于审计。"""

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(DataAgentResultArtifact)
            .where(
                DataAgentResultArtifact.expires_at.is_not(None),
                DataAgentResultArtifact.expires_at <= datetime.now(UTC),
                DataAgentResultArtifact.details_purged_at.is_(None),
            )
            .values(
                columns_json=[],
                details_purged_at=datetime.now(UTC),
            )
        )
        await db.commit()
        return int(result.rowcount or 0)


async def data_agent_evidence_maintenance_loop() -> None:
    while True:
        try:
            deleted = await purge_expired_result_artifacts()
            if deleted:
                logger.info("data_agent_result_artifact_details_purged", count=deleted)
        except Exception as exc:  # noqa: BLE001 - 周期维护失败不能终止 Worker
            logger.warning("data_agent_result_artifact_purge_failed", error=str(exc))
        await asyncio.sleep(max(60, int(settings.data_deletion_poll_seconds)))
