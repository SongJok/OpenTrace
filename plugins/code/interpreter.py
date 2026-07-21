"""
CodeInterpreterPlugin — subprocess Python in session workdir with AST guard + optional pip (allowlist).
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from sandbox_runtime.executor import sandbox_executor

logger = get_logger(__name__)
tracer = get_tracer(__name__)

_DEFAULT_TIMEOUT = 30
_WORK_ROOT = Path(tempfile.gettempdir()) / "opentrace_sandbox"

# 仅允许常见数据分析栈；生产应配合离线 wheel 或私有索引
_PIP_ALLOWLIST = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.+\-]{0,40}$")


def _session_dir(session_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id or "default")[:80]
    d = _WORK_ROOT / safe
    d.mkdir(parents=True, exist_ok=True)
    return d.resolve()


def _extract_code_from_markdown(raw: str) -> str:
    """从用户整段话中提取 ```python / ``` 代码块；否则返回原文。"""
    patterns = (
        re.compile(r"```(?:python|py)\s*\n(.*?)```", re.DOTALL | re.IGNORECASE),
        re.compile(r"```\s*\n(.*?)```", re.DOTALL),
    )
    for pat in patterns:
        m = pat.search(raw)
        if m:
            body = (m.group(1) or "").strip()
            if body:
                return body
    return raw.strip()


def _parse_inputs(query: str) -> tuple[str, list[str]]:
    q = (query or "").strip()
    if q.startswith("{"):
        data = json.loads(q)
        code = str(data.get("code", ""))
        packages = data.get("packages") or []
        if not isinstance(packages, list):
            packages = []
        return code, [str(p) for p in packages]
    return _extract_code_from_markdown(q), []


def _pip_install(packages: list[str], work_dir: Path, timeout: float) -> tuple[str, str]:
    if not packages:
        return "", ""
    args = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q"]
    for p in packages:
        if not _PIP_ALLOWLIST.match(p):
            raise ValueError(f"pip 包名不在允许模式: {p}")
        args.append(p)
    proc = subprocess.run(
        args,
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.stdout or "", proc.stderr or (proc.returncode and "pip failed") or ""


def _list_files(d: Path) -> set[str]:
    return {str(p.relative_to(d)) for p in d.rglob("*") if p.is_file()}


async def run_code_interpreter(query: str, session_id: str = "", timeout: float = _DEFAULT_TIMEOUT) -> str:
    with tracer.start_as_current_span("plugin.code_interpreter"):
        code, packages = await asyncio.to_thread(_parse_inputs, query)
        if not code.strip():
            return json.dumps(
                {
                    "error": "no code",
                    "hint": '使用 JSON {"code":"...","packages":[]} 或在消息中使用 ```python ... ``` 代码块',
                },
                ensure_ascii=False,
            )

        work_dir = _session_dir(session_id)

        pip_out, pip_err = "", ""
        if packages:
            try:
                pip_out, pip_err = await asyncio.to_thread(
                    _pip_install, packages, work_dir, min(timeout, 120.0)
                )
            except Exception as exc:  # noqa: BLE001
                return json.dumps(
                    {"error": "pip_install_failed", "detail": str(exc)},
                    ensure_ascii=False,
                )

        try:
            result = await sandbox_executor.run(
                code=code,
                session_id=session_id,
                timeout_seconds=timeout,
                packages=packages,
            )
        except subprocess.TimeoutExpired:
            return json.dumps({"error": "timeout", "seconds": timeout}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"code_interpreter run failed: {exc}")
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

        return json.dumps(
            {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "output_files": result.output_files,
                "work_dir": str(work_dir),
                "provider": result.provider,
                "provider_metadata": result.metadata,
                "pip_stdout": pip_out,
                "pip_stderr": pip_err,
            },
            ensure_ascii=False,
        )
