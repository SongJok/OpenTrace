#!/usr/bin/env bash
# 本地与 CI 共用的可复现开发依赖安装入口。
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-python}"
UV_VERSION="${UV_VERSION:-0.8.24}"
"$PYTHON_BIN" -m pip install "uv==$UV_VERSION"
"$PYTHON_BIN" -m pip install --require-hashes -r requirements-dev.lock
"$PYTHON_BIN" -m pip install --no-deps -e .
echo "OK: development dependencies installed from requirements-dev.lock"
