#!/usr/bin/env bash
# OpenTrace — 本地全栈一键启动（前端 + 后端 Docker）
# 等价: bash scripts/work/dev-boot-all-in-one.sh "$@"
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$ROOT/scripts/work/dev-boot-all-in-one.sh" "$@"