#!/bin/bash
# =============================================================================
# OpenTrace — Docker 环境快速验收
# 用法: bash scripts/verify_docker.sh
# =============================================================================
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:14100}"

echo "== verify_docker =="

if ! docker compose ps >/dev/null 2>&1; then
  echo "✗ docker compose 不可用或当前目录不是 compose 项目"
  exit 1
fi

for svc in api postgres redis agent-worker; do
  if ! docker compose ps "$svc" >/dev/null 2>&1; then
    echo "✗ 服务不存在: $svc"
    exit 1
  fi
done

health=$(curl -s --max-time 10 "$BASE_URL/api/v1/health" || true)
if [[ -z "$health" ]]; then
  echo "✗ health 无响应: $BASE_URL/api/v1/health"
  exit 1
fi

deps=$(curl -s --max-time 10 "$BASE_URL/api/v1/health/deps" || true)
if [[ -z "$deps" ]]; then
  echo "✗ health/deps 无响应: $BASE_URL/api/v1/health/deps"
  exit 1
fi

if command -v jq >/dev/null 2>&1; then
  echo "$health" | jq -e '.status == "ok"' >/dev/null || {
    echo "✗ health.status 非 ok"
    echo "$health"
    exit 1
  }

  echo "$deps" | jq -e '.status == "ok" or .status == "degraded"' >/dev/null || {
    echo "✗ deps.status 非 ok/degraded"
    echo "$deps"
    exit 1
  }

  echo "$deps" | jq -e '.database == "ok" and .redis == "ok"' >/dev/null || {
    echo "✗ database 或 redis 依赖异常"
    echo "$deps"
    exit 1
  }
else
  echo "[WARN] jq 未安装，跳过 JSON 字段级断言"
fi

echo "✓ verify_docker 通过"
