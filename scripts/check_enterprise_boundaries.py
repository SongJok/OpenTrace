#!/usr/bin/env python3
"""防止旧运行时依赖、大文件与宽泛异常债务继续增长。"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "quality" / "engineering_baseline.json"
LEGACY_ALLOWLIST = ROOT / "architecture" / "legacy_runtime_allowlist.txt"
LEGACY_MARKERS = (
    "kernel.cognitive_supervisor",
    "kernel.runtime_gateway",
    "kernel.cognitive_kernel",
)


def tracked_python_files() -> list[Path]:
    tracked = subprocess.check_output(["git", "ls-files", "*.py"], cwd=ROOT, text=True)
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "*.py"], cwd=ROOT, text=True
    )
    files = set(tracked.splitlines()) | set(untracked.splitlines())
    return [
        ROOT / line
        for line in sorted(files)
        if line and not line.startswith("tests/") and (ROOT / line).exists()
    ]


def legacy_dependents() -> set[str]:
    found = set()
    for path in tracked_python_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith("kernel/cognitive_supervisor/") or relative in {
            "kernel/runtime_gateway.py",
            "kernel/cognitive_kernel.py",
        }:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        if any(
            module == marker or module.startswith(f"{marker}.")
            for module in modules
            for marker in LEGACY_MARKERS
        ):
            found.add(f"./{relative}")
    return found


def exception_counts() -> dict[str, int]:
    wide = 0
    silent = 0
    for path in tracked_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            broad = node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id == "Exception"
            )
            wide += int(broad)
            silent += int(len(node.body) == 1 and isinstance(node.body[0], ast.Pass))
    return {"broad_exceptions": wide, "silent_pass_handlers": silent}


def main() -> int:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    errors = []
    expected_legacy = {
        line.strip()
        for line in LEGACY_ALLOWLIST.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    actual_legacy = legacy_dependents()
    additions = sorted(actual_legacy - expected_legacy)
    if additions:
        errors.append(f"新增旧运行时依赖: {additions}")

    for filename, budget in baseline["large_file_budgets"].items():
        lines = sum(1 for _ in (ROOT / filename).open(encoding="utf-8"))
        if lines > int(budget["max_lines"]):
            errors.append(f"{filename} 行数 {lines} 超过冻结预算 {budget['max_lines']}")

    counts = exception_counts()
    for key, value in counts.items():
        if value > int(baseline[key]):
            errors.append(f"{key} 从 {baseline[key]} 增长到 {value}")
    if errors:
        print("\n".join(f"FAIL: {error}" for error in errors))
        return 1
    print("OK: legacy、复杂度与异常债务未增长")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
