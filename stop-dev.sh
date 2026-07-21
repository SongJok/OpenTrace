#!/usr/bin/env bash
# OpenTrace — 本地全栈关闭
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$ROOT/scripts/work/dev-stop-all.sh" "$@"