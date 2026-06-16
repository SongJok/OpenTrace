"""v6 prep — track orchestrator_v4 imports before deleting legacy/v4."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Paths allowed to reference V4 until v6 removal.
V4_ALLOWLIST_PREFIXES = (
    "legacy/v4/",
    "kernel/orchestrator_v4.py",
    "kernel/orchestrator_v4_shim.py",
    "tests/orchestrator_v4_source.py",
    "tests/test_orchestrator_v4",
    "tests/test_vnext_architecture_contract.py",
)


def _collect_v4_import_lines() -> list[str]:
    pattern = r"from kernel\.orchestrator_v4|import kernel\.orchestrator_v4"
    for cmd in (
        ["rg", "-n", pattern, "--glob", "*.py"],
        ["grep", "-rn", "kernel.orchestrator_v4", "--include=*.py", "."],
    ):
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode in (0, 1):
            lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip() and "orchestrator_v4" in ln]
            if lines:
                return lines
    return []


def _is_allowlisted(line: str) -> bool:
    path = line.split(":", 1)[0] if ":" in line else line
    return any(path.startswith(p) or p in path for p in V4_ALLOWLIST_PREFIXES)


def test_v4_imports_only_in_allowlist():
    lines = _collect_v4_import_lines()
    offenders = [ln for ln in lines if not _is_allowlisted(ln)]
    assert not offenders, (
        "kernel.orchestrator_v4 imports outside allowlist (fix before deleting legacy/v4):\n"
        + "\n".join(offenders[:20])
    )


def test_report_v4_script_exists():
    assert (ROOT / "scripts/report_v4_imports.sh").is_file()