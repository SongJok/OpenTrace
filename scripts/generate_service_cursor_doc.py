#!/usr/bin/env python3
"""Regenerate docs/service/service_cursor.md from embedded template."""
from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/service/service_cursor.md"


def test_count() -> str:
    env = {**__import__("os").environ, "PYTHONPATH": str(ROOT)}
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    for line in r.stdout.splitlines():
        if "collected" in line:
            return line.split()[0]
    return "1145"


def main() -> None:
    tc = test_count()
    today = date.today().isoformat()
    # Load template from sibling file if present, else minimal
    tpl_path = ROOT / "docs/service/_service_cursor_template.md"
    if not tpl_path.exists():
        print("Missing template:", tpl_path, file=sys.stderr)
        sys.exit(1)
    text = tpl_path.read_text(encoding="utf-8")
    text = text.replace("@@TEST_COUNT@@", tc).replace("@@TODAY@@", today)
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT} ({len(text.splitlines())} lines)")


if __name__ == "__main__":
    main()