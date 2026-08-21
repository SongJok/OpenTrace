"""Connector 外连目标的统一网络安全校验。"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any
from urllib.parse import urlsplit


def _is_private_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


async def validate_network_target(
    endpoint: str,
    config: dict[str, Any],
    *,
    error_prefix: str = "connector",
) -> None:
    """拒绝不安全协议、未准入主机和 DNS 解析到私网的目标。"""

    parsed = urlsplit(endpoint)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError(f"{error_prefix}_endpoint_invalid")
    if parsed.scheme != "https" or not parsed.hostname:
        if not (
            parsed.scheme == "http"
            and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            and bool(config.get("allow_local_http"))
        ):
            raise RuntimeError(f"{error_prefix}_endpoint_https_required")
    allowed_hosts = {
        str(item).strip().lower() for item in config.get("allowed_hosts") or [] if str(item).strip()
    }
    if allowed_hosts and parsed.hostname.lower() not in allowed_hosts:
        raise RuntimeError(f"{error_prefix}_endpoint_host_not_allowlisted")

    allow_private = bool(config.get("allow_private_network"))
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_private_address(str(literal)) and not allow_private:
            raise RuntimeError(f"{error_prefix}_private_network_denied")
        return

    try:
        records = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise RuntimeError(f"{error_prefix}_endpoint_dns_resolution_failed") from exc
    addresses = {str(record[4][0]) for record in records}
    if not addresses:
        raise RuntimeError(f"{error_prefix}_endpoint_dns_resolution_empty")
    if not allow_private and any(_is_private_address(address) for address in addresses):
        raise RuntimeError(f"{error_prefix}_private_network_denied")
