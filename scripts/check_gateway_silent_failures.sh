#!/usr/bin/env bash
# Fail CI if gateway/api_gateway uses bare "except Exception: pass" (governance observability).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 <<'PY'
import re
import sys
from pathlib import Path

pat = re.compile(r"except Exception:\s*\n\s*pass", re.M)
bad: list[str] = []
for p in sorted(Path("gateway/api_gateway").rglob("*.py")):
    text = p.read_text(encoding="utf-8")
    if pat.search(text):
        bad.append(str(p))
if bad:
    print("=== FAIL: gateway/api_gateway contains except Exception: pass ===")
    for b in bad:
        print(b)
    sys.exit(1)
print("=== OK: no bare except Exception: pass in gateway/api_gateway ===")
PY