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
            # ClickHouse 的 80/8123/443/8443 通常是 HTTP 接口，9000/9440 才是原生 TCP。
            # 连接协议由端口推断，避免把 DBeaver 的 HTTP JDBC 地址错误地交给 asynch。
            if conn.port in {80, 443, 8123, 8443}:
                protocol = "https" if conn.port in {443, 8443} else "http"
                database = conn.database.strip() or "default"
                return f"clickhouse+{protocol}://{user}:{passwd}@{host}:{conn.port}/{database}"
            return f"clickhouse+asynch://{user}:{passwd}@{host}:{conn.port}/{conn.database}"
        if t in {"doris"}:
            return f"mysql+aiomysql://{user}:{passwd}@{host}:{conn.port}/{conn.database}"
        raise ValueError(f"unsupported data source type: {conn.source_type}")
