#!/bin/bash
# =============================================================================
# OpenTrace — Docker 环境快速验收
# 用法: bash scripts/verify_docker.sh
# =============================================================================
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:14100}"
frontend_port="${FRONTEND_PORT:-}"
if [[ -z "$frontend_port" && -f .env ]]; then
  frontend_port="$(sed -n 's/^FRONTEND_PORT=//p' .env | tail -n 1)"
fi
frontend_port="${frontend_port:-14108}"
FRONTEND_URL="${FRONTEND_URL:-http://127.0.0.1:${frontend_port}}"

echo "== verify_docker =="

if ! docker compose ps >/dev/null 2>&1; then
  echo "✗ docker compose 不可用或当前目录不是 compose 项目"
  exit 1
fi

for svc in api postgres redis agent-worker frontend; do
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

frontend_html=$(curl -s --max-time 10 "$FRONTEND_URL/chat" || true)
if [[ -z "$frontend_html" ]]; then
  echo "✗ 生产前端无响应: $FRONTEND_URL/chat"
  exit 1
fi
if [[ "$frontend_html" == *"/@vite/client"* || "$frontend_html" == *"/src/main.tsx"* ]]; then
  echo "✗ 前端返回了 Vite 开发资源"
  exit 1
fi
if ! curl -sf --max-time 10 "$FRONTEND_URL/api/v1/health" >/dev/null 2>&1; then
  echo "✗ 前端 API 反向代理无响应: $FRONTEND_URL/api/v1/health"
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

echo "✓ verify_docker 通过（含生产前端与 API 反向代理）"
