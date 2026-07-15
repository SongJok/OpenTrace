#!/usr/bin/env python3
"""Idempotently project legacy turn aggregates into canonical Responses.

Run after the expand migration and before switching all tenants. The script
uses deterministic response IDs, commits in bounded batches and can be safely
restarted. Use --dry-run for production sizing/checks.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from infra.storage.database import AsyncSessionLocal  # noqa: E402
from infra.storage.models import (  # noqa: E402
    ChatSession,
    ResponseEvent,
    ResponseItem,
    ResponseRecord,
    TraceLog,
)


def _response_id(trace_id: str) -> str:
    return f"legacy_{trace_id.replace('-', '')}"[:64]


async def backfill(*, batch_size: int, dry_run: bool) -> tuple[int, int]:
    scanned = created = 0
    cursor: tuple[datetime, str] | None = None
    while True:
        async with AsyncSessionLocal() as db:
            query = select(TraceLog).order_by(TraceLog.created_at, TraceLog.id).limit(batch_size)
            if cursor:
                created_at, row_id = cursor
                query = query.where(
                    (TraceLog.created_at > created_at)
                    | ((TraceLog.created_at == created_at) & (TraceLog.id > row_id))
                )
            rows = (await db.execute(query)).scalars().all()
            if not rows:
                break
            parents: dict[str, str | None] = {}
            for trace in rows:
                scanned += 1
                cursor = (trace.created_at, trace.id)
                if not trace.session_id:
                    continue
                response_id = _response_id(trace.id)
                if await db.get(ResponseRecord, response_id):
                    parents[trace.session_id] = response_id
                    continue
                session = await db.get(ChatSession, trace.session_id)
                if session is None or not session.user_id:
                    continue
                parent = parents.get(trace.session_id) or session.active_response_id
                if dry_run:
                    created += 1
                    parents[trace.session_id] = response_id
                    continue
                record = ResponseRecord(
                    id=response_id, conversation_id=session.id, user_id=session.user_id,
                    tenant_id=session.tenant_id, workspace_id=session.workspace_id,
                    parent_response_id=parent, request_id=trace.trace_id or f"legacy:{trace.id}",
                    idempotency_key=f"legacy:{trace.id}", status="completed", mode="migration",
                    model=trace.model, response_metadata={"migration_source": "trace_logs", "legacy_trace_id": trace.id},
                    request_payload={"input": trace.query, "store": False, "opentrace": {"memory_mode": "enabled", "execution_profile": "auto"}},
                    completed_at=trace.created_at,
                )
                db.add(record)
                await db.flush()
                db.add_all([
                    ResponseItem(id=f"item_{uuid.uuid4().hex}", response_id=response_id, sequence_number=0, item_type="input_message", role="user", content=trace.query, payload={"migration_source": "trace_logs"}),
                    ResponseItem(id=f"item_{uuid.uuid4().hex}", response_id=response_id, sequence_number=1, item_type="message", role="assistant", content=trace.response or "", payload={"decision_type": trace.decision_type, "validation_score": trace.validation_score}),
                    ResponseEvent(id=f"evt_{uuid.uuid4().hex}", response_id=response_id, sequence_number=0, event_type="response.created", payload={"response_id": response_id, "status": "in_progress"}, created_at=trace.created_at),
                    ResponseEvent(id=f"evt_{uuid.uuid4().hex}", response_id=response_id, sequence_number=1, event_type="response.completed", payload={"status": "completed", "content": trace.response or ""}, created_at=trace.created_at),
                ])
                session.active_response_id = response_id
                session.branch_root_response_id = session.branch_root_response_id or response_id
                parents[trace.session_id] = response_id
                created += 1
            if not dry_run:
                await db.commit()
    return scanned, created


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    scanned, created = await backfill(batch_size=max(1, args.batch_size), dry_run=args.dry_run)
    print({"scanned": scanned, "would_create" if args.dry_run else "created": created})


if __name__ == "__main__":
    asyncio.run(main())
