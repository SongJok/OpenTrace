#!/usr/bin/env python3
"""Ensure .env.example documents all KERNEL_FLAG_REGISTRY keys (append missing)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / ".env.example"


def main() -> int:
    import sys

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from infra.config.flag_registry import env_example_lines_for_registry, registry_env_keys

    if not ENV_EXAMPLE.exists():
        print("FAIL: .env.example missing", file=sys.stderr)
        return 1

    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    existing = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, re.M))
    needed = registry_env_keys()
    missing = sorted(needed - existing)

    if not missing:
        print("=== OK: .env.example contains all registry flag env keys ===")
        return 0

    block = "\n# Auto-synced kernel / enterprise flags (scripts/sync_env_example_to_docs.py)\n"
    for line in env_example_lines_for_registry():
        key = line.split("=", 1)[0]
        if key in missing:
            block += line + "\n"

    ENV_EXAMPLE.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
    print(f"=== APPENDED {len(missing)} keys to .env.example ===")
    for k in missing:
        print(f"  + {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())