#!/usr/bin/env python3
"""真实 PostgreSQL RLS 跨租户负向验证。"""

from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg


async def main() -> None:
    dsn = os.environ["MIGRATION_TEST_DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    connection = await asyncpg.connect(dsn)
    role = f"rls_test_{uuid.uuid4().hex[:8]}"
    try:
        await connection.execute(f'CREATE ROLE "{role}" NOLOGIN')
        await connection.execute(f'GRANT SELECT ON legal_holds TO "{role}"')
        await connection.execute(
            """INSERT INTO legal_holds
               (id, tenant_id, workspace_id, resource_type, reason, status, created_by)
               VALUES ('rls-a', 'tenant-a', 'ws-a', 'tenant', 'test', 'active', 'tester'),
                      ('rls-b', 'tenant-b', 'ws-b', 'tenant', 'test', 'active', 'tester')
               ON CONFLICT (id) DO NOTHING"""
        )
        async with connection.transaction():
            await connection.execute(f'SET LOCAL ROLE "{role}"')
            await connection.execute("SELECT set_config('app.tenant_id', 'tenant-a', true)")
            await connection.execute("SELECT set_config('app.workspace_id', 'ws-a', true)")
            rows = await connection.fetch("SELECT tenant_id, workspace_id FROM legal_holds")
            assert [(row["tenant_id"], row["workspace_id"]) for row in rows] == [
                ("tenant-a", "ws-a")
            ]
    finally:
        await connection.execute("DELETE FROM legal_holds WHERE id IN ('rls-a', 'rls-b')")
        await connection.execute(f'REVOKE ALL PRIVILEGES ON legal_holds FROM "{role}"')
        await connection.execute(f'DROP ROLE IF EXISTS "{role}"')
        await connection.close()
    print("OK: PostgreSQL RLS cross-tenant negative test passed")


if __name__ == "__main__":
    asyncio.run(main())
