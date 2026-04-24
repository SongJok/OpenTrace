#!/bin/bash
# =============================================================================
# OpenTrace — Docker 启动脚本
# 用法: bash scripts/docker_up.sh [--with-observability]
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

preflight() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "✗ docker 未安装或不可用"
    exit 1
  fi

  if ! docker info >/dev/null 2>&1; then
    echo "✗ docker daemon 未启动"
    exit 1
  fi

  if ! docker compose version >/dev/null 2>&1; then
    echo "✗ docker compose 不可用"
    exit 1
  fi

  if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "✗ .env 不存在，请先创建环境配置"
    exit 1
  fi

  if ! grep -q '^DATABASE_URL=' "$PROJECT_DIR/.env"; then
    echo "✗ .env 缺少 DATABASE_URL"
    exit 1
  fi

  if ! grep -q '^REDIS_URL=' "$PROJECT_DIR/.env"; then
    echo "✗ .env 缺少 REDIS_URL"
    exit 1
  fi
}

pull_with_retry() {
  local image="$1"
  local retries=3
  local i
  for i in $(seq 1 "$retries"); do
    echo "  ▸ 拉取镜像: $image (attempt $i/$retries)"
    if docker pull "$image"; then
      echo "  ✓ 镜像拉取成功: $image"
      return 0
    fi
    sleep $((i * 2))
  done
  echo "  ✗ 镜像拉取失败: $image"
  return 1
}

verify_after_boot() {
  local base_url="${BASE_URL:-http://127.0.0.1:14100}"

  echo "▸ 等待 API 健康检查..."
  for i in $(seq 1 50); do
    if curl -sf "$base_url/api/v1/health" >/dev/null 2>&1; then
      break
    fi
    sleep 2
    if [[ "$i" == "50" ]]; then
      echo "✗ API 健康检查失败: $base_url/api/v1/health"
      echo "  建议排障: bash scripts/docker_logs.sh api"
      exit 1
    fi
  done

  if ! curl -sf "$base_url/api/v1/health/deps" >/dev/null 2>&1; then
    echo "✗ 依赖健康检查失败: $base_url/api/v1/health/deps"
    echo "  建议排障: bash scripts/docker_logs.sh api"
    exit 1
  fi

  echo "✓ API 已就绪: $base_url"
  echo "✓ Swagger: $base_url/docs"
}

preflight

PROFILE_ARGS=()
WITH_OBS=0
if [[ "${1:-}" == "--with-observability" ]]; then
  PROFILE_ARGS+=(--profile observability)
  WITH_OBS=1
fi

if [ -z "${PYTHON_BASE_IMAGE:-}" ]; then
  export PYTHON_BASE_IMAGE="python:3.11-slim"
fi

echo "▸ 使用 Python 基础镜像: $PYTHON_BASE_IMAGE"
echo "▸ 使用 docker compose 内 PostgreSQL 服务 (postgres:5432)"

echo "▸ 预拉取基础镜像..."
pull_with_retry "redis:7-alpine"
pull_with_retry "pgvector/pgvector:pg16"
pull_with_retry "$PYTHON_BASE_IMAGE"

echo "▸ 启动 Docker 服务..."
if [ "$WITH_OBS" -eq 1 ]; then
  export TRACE_ENABLED=true
  export OTEL_EXPORTER_OTLP_ENDPOINT="http://jaeger:4317"
else
  export TRACE_ENABLED=false
fi

if [ ${#PROFILE_ARGS[@]} -gt 0 ]; then
  docker compose "${PROFILE_ARGS[@]}" up -d --build
else
  docker compose up -d --build
fi

verify_after_boot
