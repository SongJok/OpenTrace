#!/usr/bin/env python3
"""在一次性 PostgreSQL 验证连接器 Snapshot 队列的 Worker 恢复语义。"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit


def _database_url() -> str:
    raw = os.environ.get("ENTERPRISE_KNOWLEDGE_TEST_DATABASE_URL", "")
    if "migration_test" not in urlsplit(raw).path:
        raise SystemExit(
            "ENTERPRISE_KNOWLEDGE_TEST_DATABASE_URL 必须指向一次性 migration_test 数据库"
        )
    return raw.replace("postgresql://", "postgresql+asyncpg://", 1)


TEST_DATABASE_URL = _database_url()
# Worker 使用全局 AsyncSessionLocal；必须在导入数据库模块前绑定到隔离测试库。
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from infra.storage.models import (  # noqa: E402
    KnowledgeConnector,
    KnowledgeReviewTask,
    KnowledgeSource,
    KnowledgeSourcePermission,
    KnowledgeSpace,
    KnowledgeSyncItem,
    KnowledgeSyncRun,
    User,
)
from knowledge.compiler import content_hash  # noqa: E402
from knowledge.jobs import process_pending_compile_jobs  # noqa: E402
from knowledge.sync import process_pending_sync_items, retry_sync_run  # noqa: E402


async def verify() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    marker = uuid.uuid4().hex[:12]
    user_id = f"sync-owner-{marker}"
    space_id = f"sync-space-{marker}"
    connector_id = f"sync-connector-{marker}"
    run_id = f"sync-run-{marker}"
    item_id = f"sync-item-{marker}"
    failed_item_id = f"sync-item-retry-{marker}"
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add(
            User(
                id=user_id,
                email=f"{user_id}@example.com",
                display_name="Sync Owner",
                status="active",
                role="admin",
                is_active=True,
            )
        )
        await db.flush()
        db.add(
            KnowledgeSpace(
                id=space_id,
                tenant_id="sync-tenant",
                workspace_id="sync-workspace",
                owner_id=user_id,
                name="同步验收空间",
                slug=f"sync-{marker}",
                space_type="department",
                visibility="members",
                default_classification="internal",
                publish_policy="review",
            )
        )
        await db.flush()
        db.add(
            KnowledgeConnector(
                id=connector_id,
                space_id=space_id,
                tenant_id="sync-tenant",
                workspace_id="sync-workspace",
                owner_id=user_id,
                name="验收 Push",
                connector_type="push",
                status="active",
            )
        )
        await db.flush()
        db.add(
            KnowledgeSyncRun(
                id=run_id,
                connector_id=connector_id,
                tenant_id="sync-tenant",
                workspace_id="sync-workspace",
                status="pending",
                cursor_before=None,
                cursor_after="delta-1",
                stats={"batch_hash": marker, "queued": 2},
            )
        )
        await db.flush()
        db.add(
            KnowledgeSyncItem(
                id=item_id,
                run_id=run_id,
                connector_id=connector_id,
                tenant_id="sync-tenant",
                workspace_id="sync-workspace",
                external_id="policy-1",
                title="连接器同步制度",
                content="连接器同步必须先保存 ACL，再提交编译任务。",
                content_type="text",
                content_hash=content_hash("连接器同步必须先保存 ACL，再提交编译任务。"),
                authority="official",
                classification="internal",
                source_metadata={"provider": "verification"},
                acl_snapshot=[
                    {
                        "subject_type": "user",
                        "subject_id": user_id,
                        "permission": "view",
                        "inherited": False,
                    }
                ],
                status="pending",
            )
        )
        db.add(
            KnowledgeSyncItem(
                id=failed_item_id,
                run_id=run_id,
                connector_id=connector_id,
                tenant_id="sync-tenant",
                workspace_id="sync-workspace",
                external_id="policy-retry",
                title="连接器失败重试制度",
                content="失败项修复后必须可重新入队，并且整批成功后才能推进游标。",
                content_type="text",
                content_hash=content_hash(
                    "失败项修复后必须可重新入队，并且整批成功后才能推进游标。"
                ),
                authority="official",
                classification="internal",
                source_metadata={"provider": "verification"},
                acl_snapshot=[
                    {
                        "subject_type": "user",
                        "subject_id": user_id,
                        "permission": "view",
                        "expires_at": "invalid-datetime",
                    }
                ],
                status="pending",
            )
        )
        await db.commit()

    processed = await process_pending_sync_items(limit=200, worker_id="verify-sync-worker")
    assert processed >= 2
    async with AsyncSession(engine, expire_on_commit=False) as db:
        item = await db.get(KnowledgeSyncItem, item_id)
        failed_item = await db.get(KnowledgeSyncItem, failed_item_id)
        run = await db.get(KnowledgeSyncRun, run_id)
        connector = await db.get(KnowledgeConnector, connector_id)
        assert item is not None and item.status == "succeeded" and item.attempts == 1
        assert item.document_id and item.source_id
        assert failed_item is not None and failed_item.status == "failed"
        assert failed_item.attempts == 1 and "Invalid isoformat" in (failed_item.error or "")
        assert run is not None and run.status == "failed"
        assert (run.stats or {}).get("batch_hash") == marker
        assert connector is not None and connector.sync_cursor is None
        source = await db.get(KnowledgeSource, item.source_id)
        assert source is not None and source.space_id == space_id
        permission = await db.scalar(
            select(KnowledgeSourcePermission).where(
                KnowledgeSourcePermission.source_id == source.id
            )
        )
        assert permission is not None and permission.subject_id == user_id
        failed_item.acl_snapshot = [
            {
                "subject_type": "user",
                "subject_id": user_id,
                "permission": "view",
                "inherited": False,
            }
        ]
        await db.commit()

    retried = await retry_sync_run(run_id)
    assert retried == {"run_id": run_id, "requeued": 1, "status": "pending"}
    processed = await process_pending_sync_items(limit=200, worker_id="verify-retry-worker")
    assert processed >= 1
    async with AsyncSession(engine, expire_on_commit=False) as db:
        retried_item = await db.get(KnowledgeSyncItem, failed_item_id)
        run = await db.get(KnowledgeSyncRun, run_id)
        connector = await db.get(KnowledgeConnector, connector_id)
        assert retried_item is not None and retried_item.status == "succeeded"
        assert retried_item.attempts == 1
        assert run is not None and run.status == "succeeded"
        assert connector is not None and connector.sync_cursor == "delta-1"

    blocking_run_id = f"sync-run-blocking-{marker}"
    blocking_item_id = f"sync-item-blocking-{marker}"
    later_run_id = f"sync-run-later-{marker}"
    later_item_id = f"sync-item-later-{marker}"
    started_at = datetime.now(UTC)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add(
            KnowledgeSyncRun(
                id=blocking_run_id,
                connector_id=connector_id,
                tenant_id="sync-tenant",
                workspace_id="sync-workspace",
                status="failed",
                cursor_before="delta-1",
                cursor_after="delta-2",
                stats={"queued": 0, "failed": 1},
                started_at=started_at,
                completed_at=started_at,
            )
        )
        await db.flush()
        db.add(
            KnowledgeSyncItem(
                id=blocking_item_id,
                run_id=blocking_run_id,
                connector_id=connector_id,
                tenant_id="sync-tenant",
                workspace_id="sync-workspace",
                external_id="policy-blocking",
                title="顺序同步前置批次",
                content="同一连接器的后续批次必须等待前置失败批次完成。",
                content_hash=content_hash("同一连接器的后续批次必须等待前置失败批次完成。"),
                authority="official",
                classification="internal",
                status="failed",
                attempts=1,
                error="verification_failure",
                completed_at=started_at,
            )
        )
        db.add(
            KnowledgeSyncRun(
                id=later_run_id,
                connector_id=connector_id,
                tenant_id="sync-tenant",
                workspace_id="sync-workspace",
                status="pending",
                cursor_before="delta-2",
                cursor_after="delta-3",
                stats={"queued": 1},
                started_at=started_at + timedelta(seconds=1),
            )
        )
        await db.flush()
        db.add(
            KnowledgeSyncItem(
                id=later_item_id,
                run_id=later_run_id,
                connector_id=connector_id,
                tenant_id="sync-tenant",
                workspace_id="sync-workspace",
                external_id="policy-later",
                title="顺序同步后续批次",
                content="前置批次成功后，后续批次才可以领取并推进游标。",
                content_hash=content_hash("前置批次成功后，后续批次才可以领取并推进游标。"),
                authority="official",
                classification="internal",
                status="pending",
            )
        )
        await db.commit()

    blocked = await process_pending_sync_items(limit=1, worker_id="verify-order-worker")
    assert blocked == 0
    async with AsyncSession(engine, expire_on_commit=False) as db:
        later_item = await db.get(KnowledgeSyncItem, later_item_id)
        connector = await db.get(KnowledgeConnector, connector_id)
        assert later_item is not None and later_item.status == "pending"
        assert connector is not None and connector.sync_cursor == "delta-1"

    retried = await retry_sync_run(blocking_run_id)
    assert retried["requeued"] == 1
    ordered = await process_pending_sync_items(limit=200, worker_id="verify-order-worker")
    assert ordered >= 2
    async with AsyncSession(engine, expire_on_commit=False) as db:
        blocking_run = await db.get(KnowledgeSyncRun, blocking_run_id)
        later_run = await db.get(KnowledgeSyncRun, later_run_id)
        connector = await db.get(KnowledgeConnector, connector_id)
        assert blocking_run is not None and blocking_run.status == "succeeded"
        assert later_run is not None and later_run.status == "succeeded"
        assert connector is not None and connector.sync_cursor == "delta-3"

    compiled = await process_pending_compile_jobs(limit=200, worker_id="verify-compile-worker")
    assert compiled >= 1
    async with AsyncSession(engine, expire_on_commit=False) as db:
        item = await db.get(KnowledgeSyncItem, item_id)
        source = await db.get(KnowledgeSource, item.source_id) if item else None
        assert source is not None and source.status == "review"
        review = await db.scalar(
            select(KnowledgeReviewTask).where(KnowledgeReviewTask.space_id == space_id)
        )
        assert review is not None

    exhausted_run_id = f"sync-run-exhausted-{marker}"
    exhausted_item_id = f"sync-item-exhausted-{marker}"
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add(
            KnowledgeSyncRun(
                id=exhausted_run_id,
                connector_id=connector_id,
                tenant_id="sync-tenant",
                workspace_id="sync-workspace",
                status="running",
                cursor_before="delta-3",
                cursor_after="delta-4",
                stats={"running": 1},
            )
        )
        await db.flush()
        db.add(
            KnowledgeSyncItem(
                id=exhausted_item_id,
                run_id=exhausted_run_id,
                connector_id=connector_id,
                tenant_id="sync-tenant",
                workspace_id="sync-workspace",
                external_id="policy-exhausted",
                title="耗尽重试的同步项",
                content="超过最大尝试次数的失联任务必须终止为失败。",
                content_hash=content_hash("超过最大尝试次数的失联任务必须终止为失败。"),
                status="running",
                attempts=3,
                locked_by="lost-worker",
                started_at=datetime.now(UTC) - timedelta(minutes=20),
            )
        )
        await db.commit()

    await process_pending_sync_items(limit=1, worker_id="verify-reclaim-worker")
    async with AsyncSession(engine, expire_on_commit=False) as db:
        exhausted_item = await db.get(KnowledgeSyncItem, exhausted_item_id)
        exhausted_run = await db.get(KnowledgeSyncRun, exhausted_run_id)
        connector = await db.get(KnowledgeConnector, connector_id)
        assert exhausted_item is not None and exhausted_item.status == "failed"
        assert exhausted_item.error == "knowledge_sync_worker_lease_expired"
        assert exhausted_run is not None and exhausted_run.status == "failed"
        assert exhausted_run.error == "knowledge_sync_worker_lease_expired"
        assert connector is not None and connector.sync_cursor == "delta-3"
        assert connector.last_error == "knowledge_sync_worker_lease_expired"

    await engine.dispose()
    print(
        "OK: durable knowledge sync claim, retry, ordered cursor gate, "
        "lease exhaustion, ACL and compile lifecycle"
    )


if __name__ == "__main__":
    asyncio.run(verify())
