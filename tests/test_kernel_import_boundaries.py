"""Kernel must not import duplicate governance implementations (use kernel.governance)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / "kernel"

_FORBIDDEN_PREFIXES = (
    "from governance.",
    "import governance.",
)


def _py_files_under_kernel() -> list[Path]:
    return [p for p in KERNEL.rglob("*.py") if p.is_file()]


def test_kernel_no_direct_governance_package_imports():
    violations: list[str] = []
    for path in _py_files_under_kernel():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for prefix in _FORBIDDEN_PREFIXES:
                if prefix in stripped:
                    violations.append(f"{rel}: {stripped[:120]}")
                    break
    assert not violations, "kernel must use kernel.governance:\n" + "\n".join(violations[:20])