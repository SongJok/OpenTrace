#!/bin/sh
set -eu

: "${UV_VERSION:=0.8.24}"
: "${UV_BOOTSTRAP_INDEX_URL:=https://mirrors.aliyun.com/pypi/simple}"
: "${UV_BOOTSTRAP_FALLBACK_INDEX_URL:=https://pypi.tuna.tsinghua.edu.cn/simple}"
: "${UV_BOOTSTRAP_TIMEOUT:=30}"
: "${UV_BOOTSTRAP_RETRIES:=1}"
: "${UV_BOOTSTRAP_PRIMARY_MAX_SECONDS:=90}"
: "${UV_BOOTSTRAP_FALLBACK_MAX_SECONDS:=300}"

install_from_index() {
    index_url="$1"
    max_seconds="$2"
    echo "▸ 从 ${index_url} 安装 uv ${UV_VERSION}"
    PIP_EXTRA_INDEX_URL="" \
    PIP_DEFAULT_TIMEOUT="${UV_BOOTSTRAP_TIMEOUT}" \
    PIP_RETRIES="${UV_BOOTSTRAP_RETRIES}" \
    timeout "${max_seconds}" \
        python -m pip install \
        --index-url "${index_url}" \
        --prefer-binary \
        --only-binary=:all: \
        --no-deps \
        --disable-pip-version-check \
        "uv==${UV_VERSION}"
}

if install_from_index "${UV_BOOTSTRAP_INDEX_URL}" "${UV_BOOTSTRAP_PRIMARY_MAX_SECONDS}"; then
    exit 0
fi

if [ "${UV_BOOTSTRAP_FALLBACK_INDEX_URL}" != "${UV_BOOTSTRAP_INDEX_URL}" ]; then
    echo "▸ uv 主镜像安装失败，切换备用国内镜像" >&2
    if install_from_index \
        "${UV_BOOTSTRAP_FALLBACK_INDEX_URL}" \
        "${UV_BOOTSTRAP_FALLBACK_MAX_SECONDS}"; then
        exit 0
    fi
fi

echo "无法在限定时间内安装 uv ${UV_VERSION}，请检查服务器到国内 PyPI 镜像的网络。" >&2
exit 1
