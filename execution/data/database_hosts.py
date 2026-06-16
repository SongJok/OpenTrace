from __future__ import annotations

import ipaddress
import os
import re
from functools import lru_cache

from infra.config.settings import get_settings


LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})
DOCKER_INTERNAL_DATABASE_HOSTS = frozenset(
    {
        "db",
        "mysql",
        "postgres",
        "mariadb",
        "clickhouse",
        "doris",
        "redis",
        "service-db",
        "database",
    }
)
LOOPBACK_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
EXTERNAL_HOST_PATTERN = re.compile(r"^[a-z0-9.-]+$", re.IGNORECASE)


def normalize_database_host(host: str) -> str:
    return (host or "").strip()


def is_docker_internal_database_host(host: str) -> bool:
    return normalize_database_host(host).lower() in DOCKER_INTERNAL_DATABASE_HOSTS


def is_allowed_database_host(host: str) -> bool:
    normalized = normalize_database_host(host).lower()
    if not normalized or normalized in DOCKER_INTERNAL_DATABASE_HOSTS:
        return False
    if normalized in LOCAL_DATABASE_HOSTS:
        return True
    try:
        ipaddress.ip_address(normalized)
        return True
    except ValueError:
        pass
    return bool(EXTERNAL_HOST_PATTERN.match(normalized))


@lru_cache(maxsize=1)
def is_running_in_container() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return False
    return any(marker in content for marker in ("docker", "containerd", "kubepods"))


def format_database_connection_error(
    exc: BaseException,
    *,
    configured_host: str,
    port: int | None = None,
    database: str | None = None,
) -> str:
    """Turn low-level driver errors into actionable messages (Docker / loopback)."""
    raw = str(exc)
    lower = raw.lower()
    host_part = normalize_database_host(configured_host)
    resolved = resolve_database_host_for_runtime(configured_host)
    resolved_in_container = resolve_database_host_for_runtime(
        configured_host,
        containerized=True,
        docker_host_alias=get_settings().docker_host_alias,
    )
    endpoint = f"{resolved}:{port}" if port else resolved
    if host_part.lower() in LOOPBACK_DATABASE_HOSTS:
        hint = (
            f"数据源 host 为 {host_part}；在 Docker 容器内会解析为 {resolved_in_container}。"
            "请确认宿主机数据库已启动且可从容器访问（如 host-gateway / 局域网 IP）。"
        )
    else:
        hint = f"请确认数据库在 {endpoint} 可访问。"
    if "access denied" in lower or "authentication failed" in lower:
        return f"数据库认证失败：{raw}。请检查用户名和密码。{hint}"
    if "connection refused" in lower or "could not connect" in lower or "timed out" in lower:
        return f"数据库连接失败（{endpoint}）：{raw}。{hint}"
    if "does not exist" in lower or "unknown database" in lower:
        db_label = database or "（未指定）"
        return f"数据库不存在（{db_label}）：{raw}。请检查库名。"
    if "table" in lower and "not exist" in lower:
        return f"表不存在：{raw}。请检查表名或同步 schema。"
    return raw


def resolve_database_host_for_runtime(
    host: str,
    *,
    containerized: bool | None = None,
    docker_host_alias: str | None = None,
) -> str:
    sanitized = normalize_database_host(host)
    normalized = sanitized.lower()
    running_in_container = is_running_in_container() if containerized is None else containerized
    if running_in_container and normalized in LOOPBACK_DATABASE_HOSTS:
        alias = normalize_database_host(docker_host_alias or get_settings().docker_host_alias)
        return alias or "host.docker.internal"
    return sanitized
