#!/bin/sh
set -eu

: "${PYTHON_DEPENDENCY_INDEX_URL:=https://mirrors.aliyun.com/pypi/simple}"
: "${PYTHON_DEPENDENCY_FALLBACK_INDEX_URL:=https://pypi.tuna.tsinghua.edu.cn/simple}"
: "${PYTHON_DEPENDENCY_PRIMARY_MAX_SECONDS:=180}"
: "${PYTHON_DEPENDENCY_FALLBACK_MAX_SECONDS:=1200}"
: "${PYTHON_DEPENDENCY_HTTP_TIMEOUT:=60}"
: "${PYTHON_DEPENDENCY_HTTP_RETRIES:=3}"
: "${PYTHON_DEPENDENCY_FALLBACK_ATTEMPTS:=2}"
: "${UV_CONCURRENT_DOWNLOADS:=4}"
: "${UV_CONCURRENT_INSTALLS:=2}"
: "${UV_CONCURRENT_BUILDS:=1}"

install_from_index() {
    index_url="$1"
    max_seconds="$2"
    echo "▸ 从 ${index_url} 安装锁定的 Python 依赖（最长 ${max_seconds}s）"
    UV_INDEX_URL="${index_url}" \
    UV_EXTRA_INDEX_URL="" \
    UV_HTTP_TIMEOUT="${PYTHON_DEPENDENCY_HTTP_TIMEOUT}" \
    UV_HTTP_RETRIES="${PYTHON_DEPENDENCY_HTTP_RETRIES}" \
    UV_CONCURRENT_DOWNLOADS="${UV_CONCURRENT_DOWNLOADS}" \
    UV_CONCURRENT_INSTALLS="${UV_CONCURRENT_INSTALLS}" \
    UV_CONCURRENT_BUILDS="${UV_CONCURRENT_BUILDS}" \
    UV_LINK_MODE=copy \
    timeout "${max_seconds}" \
        uv pip install --system --require-hashes -r /tmp/requirements.lock
}

if install_from_index \
    "${PYTHON_DEPENDENCY_INDEX_URL}" \
    "${PYTHON_DEPENDENCY_PRIMARY_MAX_SECONDS}"; then
    exit 0
fi

if [ "${PYTHON_DEPENDENCY_FALLBACK_INDEX_URL}" != "${PYTHON_DEPENDENCY_INDEX_URL}" ]; then
    attempt=1
    while [ "${attempt}" -le "${PYTHON_DEPENDENCY_FALLBACK_ATTEMPTS}" ]; do
        echo "▸ Python 依赖主镜像失败或超时，复用缓存并切换备用国内镜像（第 ${attempt}/${PYTHON_DEPENDENCY_FALLBACK_ATTEMPTS} 次）" >&2
        if install_from_index \
            "${PYTHON_DEPENDENCY_FALLBACK_INDEX_URL}" \
            "${PYTHON_DEPENDENCY_FALLBACK_MAX_SECONDS}"; then
            exit 0
        fi
        attempt=$((attempt + 1))
    done
fi

echo "无法在限定时间内安装 Python 依赖，请检查服务器网络或配置预构建镜像。" >&2
exit 1
