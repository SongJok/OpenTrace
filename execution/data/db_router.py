from __future__ import annotations

from dataclasses import dataclass

from execution.data.database_hosts import resolve_database_host_for_runtime


@dataclass
class DBConnectionInfo:
    source_type: str
    host: str
    port: int
    database: str
    username: str
    password: str


class DBRouter:
    def build_dsn(self, conn: DBConnectionInfo) -> str:
        host = resolve_database_host_for_runtime(conn.host)
        if host.count(":") >= 2 and not host.startswith("["):
            host = f"[{host}]"
        t = (conn.source_type or "").lower()
        if t in {"postgres", "postgresql", "pg"}:
            return f"postgresql+asyncpg://{conn.username}:{conn.password}@{host}:{conn.port}/{conn.database}"
        if t in {"mysql"}:
            return f"mysql+asyncmy://{conn.username}:{conn.password}@{host}:{conn.port}/{conn.database}"
        if t in {"clickhouse"}:
            return f"clickhouse+asynch://{conn.username}:{conn.password}@{host}:{conn.port}/{conn.database}"
        if t in {"doris"}:
            return f"mysql+asyncmy://{conn.username}:{conn.password}@{host}:{conn.port}/{conn.database}"
        raise ValueError(f"unsupported data source type: {conn.source_type}")
