#!/usr/bin/env python3
"""清空 OpenTrace 全部运行数据，保留数据库结构与 Alembic 版本。

默认只预览；传入 ``--execute`` 才执行。脚本会：
1. TRUNCATE public schema 内除 alembic_version 外的全部表；
2. 清理 OpenTrace 独占的 Redis 10-15 号逻辑库；
3. 删除当前发布的 memory/COMPANY.md 运行镜像。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.config.settings import settings  # noqa: E402

COMPANY_MD_PATH = ROOT / "memory" / "COMPANY.md"
PRESERVED_TABLES = frozenset({"alembic_version"})


def _postgres_candidates(database_url: str) -> list[str]:
    normalized = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    candidates = [normalized]
    parsed = urlsplit(normalized)
    if parsed.hostname in {"postgres", "db"}:
        userinfo = ""
        if parsed.username:
            userinfo = parsed.username
            if parsed.password:
                userinfo += f":{parsed.password}"
            userinfo += "@"
        port = parsed.port or 5432
        fallback = urlunsplit(
            (
                parsed.scheme,
                f"{userinfo}127.0.0.1:{port}",
                parsed.path,
                parsed.query,
                parsed.fragment,
            )
        )
        candidates.append(fallback)
    return candidates


def _safe_database_label(database_url: str) -> str:
    parsed = urlsplit(database_url)
    return f"{parsed.hostname or '?'}:{parsed.port or 5432}/{parsed.path.lstrip('/')}"


def _redis_database_urls(redis_url: str, database: int) -> list[str]:
    """生成容器内地址与宿主机映射地址，且显式固定目标逻辑库。"""

    parsed = urlsplit(redis_url)
    primary = urlunsplit(
        (parsed.scheme, parsed.netloc, f"/{database}", parsed.query, parsed.fragment)
    )
    candidates = [primary]
    if parsed.hostname == "redis":
        userinfo = ""
        if parsed.username:
            userinfo = parsed.username
            if parsed.password:
                userinfo += f":{parsed.password}"
            userinfo += "@"
        candidates.append(
            urlunsplit(
                (
                    parsed.scheme,
                    f"{userinfo}127.0.0.1:6380",
                    f"/{database}",
                    parsed.query,
                    parsed.fragment,
                )
            )
        )
    return candidates


async def _inspect_database(database_url: str) -> tuple[list[tuple[str, int]], str]:
    last_error: Exception | None = None
    for candidate in _postgres_candidates(database_url):
        engine = create_async_engine(candidate, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                rows = await connection.execute(
                    text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                        ORDER BY table_name
                        """
                    )
                )
                tables = [str(row[0]) for row in rows if str(row[0]) not in PRESERVED_TABLES]
                counts: list[tuple[str, int]] = []
                preparer = connection.dialect.identifier_preparer
                for table in tables:
                    quoted = preparer.quote(table)
                    count = await connection.scalar(text(f"SELECT count(*) FROM public.{quoted}"))
                    counts.append((table, int(count or 0)))
                return counts, candidate
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        finally:
            await engine.dispose()
    raise RuntimeError(f"无法连接数据库：{last_error}")


async def _truncate_database(database_url: str, tables: list[str]) -> None:
    if not tables:
        return
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            preparer = connection.dialect.identifier_preparer
            targets = ", ".join(f"public.{preparer.quote(table)}" for table in sorted(tables))
            await connection.execute(text(f"TRUNCATE TABLE {targets} RESTART IDENTITY CASCADE"))
    finally:
        await engine.dispose()


async def _clear_redis() -> list[int]:
    import redis.asyncio as redis

    cleared: list[int] = []
    for database in sorted(
        {
            settings.redis_session_db,
            settings.redis_cache_db,
            settings.redis_memory_db,
            settings.redis_queue_db,
            settings.redis_rate_limit_db,
            settings.redis_pubsub_db,
        }
    ):
        # redis-py 规定 URL 路径中的逻辑库优先于 ``db=`` 参数，因此必须重写
        # ``/10`` 为目标库路径，不能只把 database 作为关键字参数传入。
        last_error: Exception | None = None
        for database_url in _redis_database_urls(settings.redis_url, database):
            client = redis.Redis.from_url(database_url)
            try:
                await client.flushdb()
                cleared.append(database)
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            finally:
                await client.aclose()
        if last_error is not None:
            raise RuntimeError(f"Redis DB {database} 清理失败：{last_error}") from last_error
    return cleared


async def main() -> int:
    parser = argparse.ArgumentParser(description="清空全部 OpenTrace 运行数据")
    parser.add_argument("--execute", action="store_true", help="执行清理；不传时只预览")
    parser.add_argument("--database-url", default=settings.database_url, help="覆盖数据库连接")
    parser.add_argument("--skip-redis", action="store_true", help="不清理 Redis 逻辑库")
    parser.add_argument(
        "--keep-company-file", action="store_true", help="保留 memory/COMPANY.md 运行镜像"
    )
    args = parser.parse_args()

    counts, resolved_url = await _inspect_database(args.database_url)
    populated = [(table, count) for table, count in counts if count]
    print(f"数据库：{_safe_database_label(resolved_url)}")
    print(
        f"业务表：{len(counts)}；有数据的表：{len(populated)}；总行数：{sum(c for _, c in counts)}"
    )
    for table, count in populated:
        print(f"  {table}: {count}")
    print("保留表：alembic_version")

    if not args.execute:
        print("预览完成；传入 --execute 才会实际清理。")
        return 0

    await _truncate_database(resolved_url, [table for table, _count in counts])
    if not args.skip_redis:
        cleared = await _clear_redis()
        print("已清理 Redis 逻辑库：" + ", ".join(str(item) for item in cleared))
    if not args.keep_company_file and COMPANY_MD_PATH.exists():
        COMPANY_MD_PATH.unlink()
        print(f"已删除企业大脑运行镜像：{COMPANY_MD_PATH}")

    remaining, _resolved = await _inspect_database(resolved_url)
    remaining_rows = sum(count for _table, count in remaining)
    if remaining_rows:
        raise RuntimeError(f"清理校验失败，仍有 {remaining_rows} 行业务数据")
    print("清理完成并校验通过：全部业务表为 0 行，数据库结构与 alembic_version 已保留。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
