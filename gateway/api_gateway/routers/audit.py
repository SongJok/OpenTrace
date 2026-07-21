from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import AuditLog, User

router = APIRouter()


def _parse_dt(s: Optional[str]) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


@router.get('/audit/logs')
async def list_audit_logs(
    start: Optional[str] = None,
    end: Optional[str] = None,
    action: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conds = [AuditLog.user_id == current_user.id]
    st = _parse_dt(start)
    ed = _parse_dt(end)
    if st:
        conds.append(AuditLog.created_at >= st)
    if ed:
        conds.append(AuditLog.created_at <= ed)
    if action:
        conds.append(AuditLog.action == action)

    r = await db.execute(select(AuditLog).where(and_(*conds)).order_by(AuditLog.created_at.desc()).limit(500))
    rows = r.scalars().all()
    return {
        'items': [
            {
                'id': x.id,
                'user_id': x.user_id,
                'action': x.action,
                'resource_type': x.resource_type,
                'resource_id': x.resource_id,
                'payload': json.loads(x.payload_json or '{}'),
                'created_at': x.created_at.isoformat() if x.created_at else None,
            }
            for x in rows
        ]
    }


@router.get('/audit/export')
async def export_audit_logs(
    start: Optional[str] = None,
    end: Optional[str] = None,
    action: Optional[str] = None,
    format: str = 'json',
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await list_audit_logs(start=start, end=end, action=action, current_user=current_user, db=db)
    if format == 'csv':
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['id', 'user_id', 'action', 'resource_type', 'resource_id', 'payload', 'created_at'])
        for x in data['items']:
            w.writerow([x['id'], x['user_id'], x['action'], x['resource_type'], x['resource_id'], json.dumps(x['payload'], ensure_ascii=False), x['created_at']])
        return PlainTextResponse(buf.getvalue(), media_type='text/csv')
    return data
