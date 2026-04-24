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
