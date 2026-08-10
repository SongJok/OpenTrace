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
    ! -path './frontend/node_modules/*' \
    ! -path './frontend/dist/*' \
    ! -path './frontend/.env' \
    ! -path './frontend/.env.*' \
    ! -path './tests/*' \
    ! -path './docs/*' \
    ! -path './.mypy_cache/*' \
    ! -path './.pytest_cache/*' \
    ! -path './.ruff_cache/*' \
    -exec cksum {} + | cksum | awk '{print $1}'
}

frontend_base_url() {
  local frontend_port="${FRONTEND_PORT:-}"
  if [ -z "$frontend_port" ] && [ -f "$PROJECT_DIR/.env" ]; then
    frontend_port="$(sed -n 's/^FRONTEND_PORT=//p' "$PROJECT_DIR/.env" | tail -n 1)"
  fi
  frontend_port="${frontend_port:-14108}"
  printf 'http://127.0.0.1:%s' "$frontend_port"
}

verify_after_boot() {
  local base_url="${BASE_URL:-http://127.0.0.1:14100}"
  local frontend_url="${FRONTEND_URL:-$(frontend_base_url)}"
  local frontend_html

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

  echo "▸ 等待生产前端健康检查..."
  for i in $(seq 1 20); do
    frontend_html="$(curl -fsS --max-time 5 "$frontend_url/chat" 2>/dev/null || true)"
    if [ -n "$frontend_html" ]; then
      break
    fi
    sleep 1
    if [[ "$i" == "20" ]]; then
      echo "✗ 前端健康检查失败: $frontend_url/chat"
      echo "  建议排障: bash scripts/docker_logs.sh frontend"
      exit 1
    fi
  done

  if [[ "$frontend_html" == *"/@vite/client"* || "$frontend_html" == *"/src/main.tsx"* ]]; then
    echo "✗ 前端仍在提供 Vite 开发资源，未使用生产构建产物"
    exit 1
  fi

  if ! curl -sf --max-time 10 "$frontend_url/api/v1/health" >/dev/null 2>&1; then
    echo "✗ 前端 API 反向代理检查失败: $frontend_url/api/v1/health"
    echo "  建议排障: bash scripts/docker_logs.sh frontend"
    exit 1
  fi

  echo "✓ 生产前端已就绪: $frontend_url"
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
if [ -z "${FRONTEND_NODE_BASE_IMAGE:-}" ]; then
  export FRONTEND_NODE_BASE_IMAGE="docker.m.daocloud.io/library/node:20-alpine"
fi
if [ -z "${FRONTEND_NGINX_BASE_IMAGE:-}" ]; then
  export FRONTEND_NGINX_BASE_IMAGE="docker.m.daocloud.io/library/nginx:alpine"
fi
REMOTE_APP_IMAGE="${OPENTRACE_IMAGE:-}"
export OPENTRACE_IMAGE="${OPENTRACE_IMAGE:-opentrace-app:local}"
export OPENTRACE_FRONTEND_IMAGE="${OPENTRACE_FRONTEND_IMAGE:-opentrace-frontend:local}"
export OPENTRACE_BUILD_FINGERPRINT="$(source_fingerprint)"
export OPENTRACE_FRONTEND_BUILD_FINGERPRINT="$OPENTRACE_BUILD_FINGERPRINT"

echo "▸ 使用 Python 基础镜像: $PYTHON_BASE_IMAGE"
echo "▸ 使用前端 Node 基础镜像: $FRONTEND_NODE_BASE_IMAGE"
echo "▸ 使用前端 Nginx 基础镜像: $FRONTEND_NGINX_BASE_IMAGE"
echo "▸ 使用 OpenTrace 应用镜像: $OPENTRACE_IMAGE"
echo "▸ 使用 OpenTrace 前端镜像: $OPENTRACE_FRONTEND_IMAGE"
echo "▸ 当前源码指纹: ${OPENTRACE_BUILD_FINGERPRINT:0:12}"
echo "▸ 使用 docker compose 内 PostgreSQL 服务 (postgres:5432)"
echo "▸ Python 依赖主镜像: ${PYTHON_DEPENDENCY_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}"
echo "▸ Python 依赖备用镜像: ${PYTHON_DEPENDENCY_FALLBACK_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
echo "▸ 依赖安装器: uv ${UV_VERSION:-0.8.24}（请求超时 ${PYTHON_DEPENDENCY_HTTP_TIMEOUT:-60}s，重试 ${PYTHON_DEPENDENCY_HTTP_RETRIES:-3} 次）"
echo "▸ 备用源整层重试: ${PYTHON_DEPENDENCY_FALLBACK_ATTEMPTS:-2} 次"
echo "▸ 依赖并发: 下载 ${UV_CONCURRENT_DOWNLOADS:-4} / 安装 ${UV_CONCURRENT_INSTALLS:-2} / 构建 ${UV_CONCURRENT_BUILDS:-1}"
echo "▸ uv 引导镜像: ${UV_BOOTSTRAP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}"
echo "▸ uv 引导备用镜像: ${UV_BOOTSTRAP_FALLBACK_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

if [ "$PULL_IMAGES" -eq 1 ]; then
  echo "▸ 更新所需镜像..."
  pull_with_retry "redis:7-alpine"
  pull_with_retry "pgvector/pgvector:pg16"
  pull_with_retry "$FRONTEND_NODE_BASE_IMAGE"
  pull_with_retry "$FRONTEND_NGINX_BASE_IMAGE"
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
  if docker image inspect "$OPENTRACE_IMAGE" >/dev/null 2>&1 \
    && docker image inspect "$OPENTRACE_FRONTEND_IMAGE" >/dev/null 2>&1; then
    IMAGE_FINGERPRINT="$(
      docker image inspect \
        --format '{{ index .Config.Labels "org.opentrace.build-fingerprint" }}' \
        "$OPENTRACE_IMAGE" 2>/dev/null || true
    )"
    FRONTEND_IMAGE_FINGERPRINT="$(
      docker image inspect \
        --format '{{ index .Config.Labels "org.opentrace.build-fingerprint" }}' \
        "$OPENTRACE_FRONTEND_IMAGE" 2>/dev/null || true
    )"
    if [ "$IMAGE_FINGERPRINT" == "$OPENTRACE_BUILD_FINGERPRINT" ] \
      && [ "$FRONTEND_IMAGE_FINGERPRINT" == "$OPENTRACE_FRONTEND_BUILD_FINGERPRINT" ]; then
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
  BUILD_ARGS+=(api frontend)
  echo "▸ 构建应用镜像（API 与 Worker 共用）和生产前端镜像..."
  DOCKER_BUILDKIT=1 BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}" \
    docker compose "${BUILD_ARGS[@]}"
else
  if ! docker image inspect "$OPENTRACE_IMAGE" >/dev/null 2>&1 \
    || ! docker image inspect "$OPENTRACE_FRONTEND_IMAGE" >/dev/null 2>&1; then
    echo "✗ 应用或前端镜像不存在: $OPENTRACE_IMAGE / $OPENTRACE_FRONTEND_IMAGE"
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
