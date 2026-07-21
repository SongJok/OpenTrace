from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from infra.observability.logger import get_logger
from sandbox_runtime.providers.base import SandboxRequest, SandboxResult
from sandbox_runtime.providers.firecracker import FirecrackerProvider
from sandbox_runtime.providers.gvisor import GVisorProvider
from sandbox_runtime.providers.local_ast import LocalASTProvider

logger = get_logger(__name__)

_WORK_ROOT = Path(tempfile.gettempdir()) / "opentrace_sandbox"


def _session_dir(session_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id or "default")[:80]
    d = _WORK_ROOT / safe
    d.mkdir(parents=True, exist_ok=True)
    return d.resolve()


class SandboxExecutor:
    def __init__(self) -> None:
        self.local = LocalASTProvider()
        self.gvisor = GVisorProvider()
        self.firecracker = FirecrackerProvider()

    def _select_provider_name(self) -> str:
        return (os.getenv("SANDBOX_PROVIDER") or "local_ast").strip().lower()

    async def run(self, code: str, session_id: str, timeout_seconds: float = 30.0, packages: list[str] | None = None) -> SandboxResult:
        req = SandboxRequest(
            code=code,
            session_id=session_id,
            work_dir=_session_dir(session_id),
            timeout_seconds=timeout_seconds,
            packages=packages or [],
        )

        target = self._select_provider_name()
        provider = self.local
        if target == "gvisor":
            provider = self.gvisor
        elif target == "firecracker":
            provider = self.firecracker

        result = await provider.run(req)
        if result.returncode == 127 and provider.name != "local_ast":
            logger.warning(f"sandbox provider {provider.name} unavailable; fallback to local_ast")
            result = await self.local.run(req)
            result.metadata["fallback_from"] = provider.name
        return result


sandbox_executor = SandboxExecutor()
