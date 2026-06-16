#!/usr/bin/env bash
# 报告仍引用 kernel.orchestrator_v4 的 Python 文件（架构债跟踪，不修改代码）
set -euo pipefail
cd "$(dirname "$0")/.."
echo "=== kernel.orchestrator_v4 imports (should be empty in production paths) ==="
if command -v rg >/dev/null 2>&1; then
  rg -n 'from kernel\.orchestrator_v4|import kernel\.orchestrator_v4' --glob '*.py' || true
else
  grep -rn 'from kernel\.orchestrator_v4\|import kernel\.orchestrator_v4' --include='*.py' . 2>/dev/null || true
fi
echo ""
echo "=== legacy.v4 imports (allowed for V4 fallback) ==="
if command -v rg >/dev/null 2>&1; then
  rg -n 'legacy\.v4' --glob '*.py' | head -40 || true
else
  grep -rn 'legacy\.v4' --include='*.py' . 2>/dev/null | head -40 || true
fi