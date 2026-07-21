#!/bin/bash
# =============================================================================
# OpenTrace — Docker 启动脚本
# 用法:
#   bash scripts/docker_up.sh
#   bash scripts/docker_up.sh --build
#   bash scripts/docker_up.sh --rebuild
#   bash scripts/docker_up.sh --pull
#   bash scripts/docker_up.sh --with-observability
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

source_fingerprint() {
  if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    {
      git rev-parse HEAD
      git diff --no-ext-diff --binary
      git diff --cached --no-ext-diff --binary
      while IFS= read -r -d '' file; do
        printf '%s\0' "$file"
        git hash-object "$file"
      done < <(git ls-files --others --exclude-standard -z)
    } | git hash-object --stdin
    return
  fi

  find . -type f \
    ! -path './.git/*' \
    ! -path './.venv/*' \
    ! -path './frontend/*' \
    ! -path './tests/*' \
    ! -path './docs/*' \
    ! -path './.mypy_cache/*' \
    ! -path './.pytest_cache/*' \
    ! -path './.ruff_cache/*' \
    -exec cksum {} + | cksum | awk '{print $1}'
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
BUILD_MODE="auto"
PULL_IMAGES=0
for arg in "$@"; do
  case "$arg" in
    --with-observability)
      PROFILE_ARGS+=(--profile observability)
      WITH_OBS=1
      ;;
    --build) BUILD_MODE="build" ;;
    --rebuild) BUILD_MODE="rebuild" ;;
    --no-build) BUILD_MODE="none" ;;
    --pull) PULL_IMAGES=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "未知参数: $arg"
      exit 1
      ;;
  esac
done

if [ -z "${PYTHON_BASE_IMAGE:-}" ]; then
  export PYTHON_BASE_IMAGE="python:3.11-slim"
fi
REMOTE_APP_IMAGE="${OPENTRACE_IMAGE:-}"
export OPENTRACE_IMAGE="${OPENTRACE_IMAGE:-opentrace-app:local}"
export OPENTRACE_BUILD_FINGERPRINT="$(source_fingerprint)"

echo "▸ 使用 Python 基础镜像: $PYTHON_BASE_IMAGE"
echo "▸ 使用 OpenTrace 应用镜像: $OPENTRACE_IMAGE"
echo "▸ 当前源码指纹: ${OPENTRACE_BUILD_FINGERPRINT:0:12}"
echo "▸ 使用 docker compose 内 PostgreSQL 服务 (postgres:5432)"

if [ "$PULL_IMAGES" -eq 1 ]; then
  echo "▸ 更新所需镜像..."
  pull_with_retry "redis:7-alpine"
  pull_with_retry "pgvector/pgvector:pg16"
  if [ -n "$REMOTE_APP_IMAGE" ]; then
    pull_with_retry "$OPENTRACE_IMAGE"
  else
    pull_with_retry "$PYTHON_BASE_IMAGE"
  fi
  if [ "$WITH_OBS" -eq 1 ]; then
    pull_with_retry "prom/prometheus:latest"
    pull_with_retry "jaegertracing/all-in-one:latest"
  fi
fi

if [ "$BUILD_MODE" == "auto" ]; then
  if docker image inspect "$OPENTRACE_IMAGE" >/dev/null 2>&1; then
    IMAGE_FINGERPRINT="$(
      docker image inspect \
        --format '{{ index .Config.Labels "org.opentrace.build-fingerprint" }}' \
        "$OPENTRACE_IMAGE" 2>/dev/null || true
    )"
    if [ "$IMAGE_FINGERPRINT" == "$OPENTRACE_BUILD_FINGERPRINT" ]; then
      BUILD_MODE="none"
    else
      BUILD_MODE="build"
      echo "▸ 检测到代码或依赖变化，将执行缓存增量构建"
    fi
  else
    BUILD_MODE="build"
    echo "▸ 首次启动未找到应用镜像，将执行一次构建"
  fi
fi

if [ "$BUILD_MODE" == "build" ] || [ "$BUILD_MODE" == "rebuild" ]; then
  BUILD_ARGS=(build)
  if [ "$BUILD_MODE" == "rebuild" ]; then
    BUILD_ARGS+=(--no-cache)
  fi
  if [ "$PULL_IMAGES" -eq 1 ]; then
    BUILD_ARGS+=(--pull)
  fi
  BUILD_ARGS+=(api)
  echo "▸ 构建统一应用镜像（API 与 Worker 共用）..."
  DOCKER_BUILDKIT=1 docker compose "${BUILD_ARGS[@]}"
else
  if ! docker image inspect "$OPENTRACE_IMAGE" >/dev/null 2>&1; then
    echo "✗ 应用镜像不存在: $OPENTRACE_IMAGE"
    echo "  请执行: bash start.sh --build"
    exit 1
  fi
  echo "▸ 复用已有应用镜像；代码或依赖有变化时使用 --build"
fi

echo "▸ 启动 Docker 服务..."
if [ "$WITH_OBS" -eq 1 ]; then
  export TRACE_ENABLED=true
  export OTEL_EXPORTER_OTLP_ENDPOINT="http://jaeger:4317"
else
  export TRACE_ENABLED=false
fi

COMPOSE_CMD=(docker compose)
if [ ${#PROFILE_ARGS[@]} -gt 0 ]; then
  COMPOSE_CMD+=("${PROFILE_ARGS[@]}")
fi
"${COMPOSE_CMD[@]}" up -d --no-build

verify_after_boot
