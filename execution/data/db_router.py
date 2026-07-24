from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

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
        user = quote_plus(conn.username)
        passwd = quote_plus(conn.password)
        t = (conn.source_type or "").lower()
        if t in {"postgres", "postgresql", "pg"}:
            return f"postgresql+asyncpg://{user}:{passwd}@{host}:{conn.port}/{conn.database}"
        if t in {"mysql"}:
            return f"mysql+aiomysql://{user}:{passwd}@{host}:{conn.port}/{conn.database}"
        if t in {"clickhouse"}:
            return f"clickhouse+asynch://{user}:{passwd}@{host}:{conn.port}/{conn.database}"
        if t in {"doris"}:
            return f"mysql+aiomysql://{user}:{passwd}@{host}:{conn.port}/{conn.database}"
        raise ValueError(f"unsupported data source type: {conn.source_type}")
