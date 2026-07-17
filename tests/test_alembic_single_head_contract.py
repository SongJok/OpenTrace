"""Alembic must have a single head after merge revision."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_alembic_migrations_are_not_gitignored():
    gitignore_lines = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "alembic/versions/*.py" not in gitignore_lines


def test_alembic_single_head():
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip() and "(head)" in ln]
    assert len(lines) == 1, f"expected 1 head, got {lines!r}: {proc.stdout}"
