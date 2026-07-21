"""Restricted subprocess runner for installed Python skills."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from infra.config.settings import settings

_BOOTSTRAP = r"""
import importlib.util, inspect, json, sys
path = sys.argv[1]
payload = json.loads(sys.stdin.read() or "{}")
spec = importlib.util.spec_from_file_location("opentrace_installed_skill", path)
if spec is None or spec.loader is None:
    raise RuntimeError("skill_entrypoint_not_loadable")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
execute = getattr(module, "execute", None)
if execute is None:
    raise RuntimeError("skill_execute_function_missing")
value = execute(payload)
if inspect.isawaitable(value):
    import asyncio
    value = asyncio.run(value)
print(json.dumps({"success": True, "output": value}, ensure_ascii=False, default=str))
"""


def _limits() -> None:
    try:
        import resource

        memory = 512 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_FSIZE, (5 * 1024 * 1024, 5 * 1024 * 1024))
    except Exception:
        return


def execute_python_skill(skill_root: Path, entrypoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not bool(getattr(settings, "skills_subprocess_execution_enabled", False)):
        return {"success": False, "error": "skill_subprocess_execution_disabled"}
    root = skill_root.resolve()
    target = (root / entrypoint).resolve()
    if root not in target.parents or not target.is_file() or target.suffix != ".py":
        return {"success": False, "error": "invalid_skill_entrypoint"}
    timeout = max(1, min(int(getattr(settings, "skills_execution_timeout_seconds", 10)), 60))
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "LANG": "C.UTF-8",
    }
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", _BOOTSTRAP, str(target)],
            input=json.dumps(payload, ensure_ascii=False, default=str),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            cwd=str(root),
            env=environment,
            preexec_fn=_limits if os.name == "posix" else None,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "skill_execution_timeout", "isolation": "subprocess"}
    if completed.returncode != 0:
        return {
            "success": False,
            "error": (completed.stderr or "skill_execution_failed")[-2000:],
            "isolation": "subprocess",
        }
    try:
        result = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"success": False, "error": "invalid_skill_output", "isolation": "subprocess"}
    return {**result, "isolation": "subprocess"}
