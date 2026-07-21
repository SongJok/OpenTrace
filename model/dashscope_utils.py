"""
Shared DashScope helpers for API key resolution and temporary network policy.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

_DASHSCOPE_HOSTS = ("dashscope.aliyuncs.com", ".aliyuncs.com")


def resolve_dashscope_api_key(*candidates: str | None) -> str:
    for candidate in candidates:
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return ""


@contextmanager
def dashscope_proxy_allowlist() -> Iterator[None]:
    original = {k: os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "NO_PROXY", "no_proxy")}
    try:
        for key in ("NO_PROXY", "no_proxy"):
            current = os.environ.get(key, "")
            parts = [p.strip() for p in current.split(",") if p.strip()]
            for host in _DASHSCOPE_HOSTS:
                if host not in parts:
                    parts.append(host)
            os.environ[key] = ",".join(parts)
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
