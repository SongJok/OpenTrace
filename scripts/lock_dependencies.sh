#!/usr/bin/env bash
# 使用 Python 3.11 基准生成通用 uv 锁与 pip hash 锁。
set -euo pipefail
cd "$(dirname "$0")/.."

UV_BIN="${UV_BIN:-uv}"
"$UV_BIN" lock --python 3.11
"$UV_BIN" export --locked --no-dev --no-emit-project --output-file requirements.lock
"$UV_BIN" export --locked --extra dev --no-emit-project --output-file requirements-dev.lock

echo "OK: uv.lock / requirements.lock / requirements-dev.lock 已同步"
