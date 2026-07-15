#!/usr/bin/env bash
# Fail CI if vNext kernel paths use bare "except Exception: pass".
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 <<'PY'
import re
import sys
from pathlib import Path

pat = re.compile(r"except Exception:\s*\n\s*pass", re.M)
roots = [
    "kernel/governance",
    "kernel/runtime",
    "kernel/cognitive_supervisor",
    "kernel/capability_runtime",
    "kernel/agent_runtime",
    "memory/fabric",
    "control_plane",
    "world",
]
skip_fragments = ("tests/",)
bad: list[str] = []
for root in roots:
    p = Path(root)
    if not p.exists():
        continue
    for f in sorted(p.rglob("*.py")):
        s = str(f)
        if any(x in s for x in skip_fragments):
            continue
        if pat.search(f.read_text(encoding="utf-8")):
            bad.append(s)
if bad:
    print("=== FAIL: bare except Exception: pass in vNext kernel paths ===")
    for b in bad:
        print(b)
    sys.exit(1)
print("=== OK: no bare except Exception: pass in vNext kernel paths ===")
PY
