from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

from plugins.code.safe_ast import assert_code_ast_safe
from sandbox_runtime.providers.base import SandboxProvider, SandboxRequest, SandboxResult


class LocalASTProvider(SandboxProvider):
    name = "local_ast"

    def _list_files(self, d: Path) -> set[str]:
        return {str(p.relative_to(d)) for p in d.rglob("*") if p.is_file()}

    async def run(self, req: SandboxRequest) -> SandboxResult:
        await asyncio.to_thread(assert_code_ast_safe, req.code)
        before = await asyncio.to_thread(self._list_files, req.work_dir)

        script = req.work_dir / f"_user_{int(time.time() * 1000)}.py"
        script.write_text(req.code, encoding="utf-8")

        def _run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(script)],
                cwd=str(req.work_dir),
                capture_output=True,
                text=True,
                timeout=req.timeout_seconds,
            )

        try:
            proc = await asyncio.to_thread(_run)
        finally:
            try:
                script.unlink(missing_ok=True)
            except OSError:
                pass

        after = await asyncio.to_thread(self._list_files, req.work_dir)
        return SandboxResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            returncode=proc.returncode,
            output_files=sorted(after - before),
            provider=self.name,
        )
