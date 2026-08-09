ARG PYTHON_BASE_IMAGE=python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

WORKDIR /app

ARG UV_VERSION=0.8.24
ARG UV_BOOTSTRAP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG UV_BOOTSTRAP_FALLBACK_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG UV_BOOTSTRAP_TIMEOUT=30
ARG UV_BOOTSTRAP_RETRIES=1
ARG UV_BOOTSTRAP_PRIMARY_MAX_SECONDS=90
ARG UV_BOOTSTRAP_FALLBACK_MAX_SECONDS=300
ARG PYTHON_DEPENDENCY_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG PYTHON_DEPENDENCY_FALLBACK_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PYTHON_DEPENDENCY_PRIMARY_MAX_SECONDS=180
ARG PYTHON_DEPENDENCY_FALLBACK_MAX_SECONDS=1200
ARG PYTHON_DEPENDENCY_HTTP_TIMEOUT=60
ARG PYTHON_DEPENDENCY_HTTP_RETRIES=3
ARG PYTHON_DEPENDENCY_FALLBACK_ATTEMPTS=2
ARG UV_CONCURRENT_DOWNLOADS=4
ARG UV_CONCURRENT_INSTALLS=2
ARG UV_CONCURRENT_BUILDS=1

COPY scripts/install_uv.sh /usr/local/bin/opentrace-install-uv
RUN --mount=type=cache,target=/root/.cache/pip \
    UV_VERSION="${UV_VERSION}" \
    UV_BOOTSTRAP_INDEX_URL="${UV_BOOTSTRAP_INDEX_URL}" \
    UV_BOOTSTRAP_FALLBACK_INDEX_URL="${UV_BOOTSTRAP_FALLBACK_INDEX_URL}" \
    UV_BOOTSTRAP_TIMEOUT="${UV_BOOTSTRAP_TIMEOUT}" \
    UV_BOOTSTRAP_RETRIES="${UV_BOOTSTRAP_RETRIES}" \
    UV_BOOTSTRAP_PRIMARY_MAX_SECONDS="${UV_BOOTSTRAP_PRIMARY_MAX_SECONDS}" \
    UV_BOOTSTRAP_FALLBACK_MAX_SECONDS="${UV_BOOTSTRAP_FALLBACK_MAX_SECONDS}" \
    sh /usr/local/bin/opentrace-install-uv

COPY requirements.lock /tmp/requirements.lock
COPY scripts/install_python_dependencies.sh /usr/local/bin/opentrace-install-dependencies
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    PYTHON_DEPENDENCY_INDEX_URL="${PYTHON_DEPENDENCY_INDEX_URL}" \
    PYTHON_DEPENDENCY_FALLBACK_INDEX_URL="${PYTHON_DEPENDENCY_FALLBACK_INDEX_URL}" \
    PYTHON_DEPENDENCY_PRIMARY_MAX_SECONDS="${PYTHON_DEPENDENCY_PRIMARY_MAX_SECONDS}" \
    PYTHON_DEPENDENCY_FALLBACK_MAX_SECONDS="${PYTHON_DEPENDENCY_FALLBACK_MAX_SECONDS}" \
    PYTHON_DEPENDENCY_HTTP_TIMEOUT="${PYTHON_DEPENDENCY_HTTP_TIMEOUT}" \
    PYTHON_DEPENDENCY_HTTP_RETRIES="${PYTHON_DEPENDENCY_HTTP_RETRIES}" \
    PYTHON_DEPENDENCY_FALLBACK_ATTEMPTS="${PYTHON_DEPENDENCY_FALLBACK_ATTEMPTS}" \
    UV_CONCURRENT_DOWNLOADS="${UV_CONCURRENT_DOWNLOADS}" \
    UV_CONCURRENT_INSTALLS="${UV_CONCURRENT_INSTALLS}" \
    UV_CONCURRENT_BUILDS="${UV_CONCURRENT_BUILDS}" \
    sh /usr/local/bin/opentrace-install-dependencies

COPY . .
RUN groupadd --gid 10001 opentrace \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin opentrace \
    && mkdir -p \
        /app/skills/catalog_mirror \
        /app/skills/installed \
        /var/lib/opentrace/objects \
        /var/lib/opentrace/dws \
    && chown -R 10001:10001 /app /var/lib/opentrace

ARG OPENTRACE_BUILD_FINGERPRINT=unknown
LABEL org.opentrace.build-fingerprint="${OPENTRACE_BUILD_FINGERPRINT}"

ENV PYTHONPATH=/app
ENV HOME=/home/opentrace
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=120

EXPOSE 14100
USER 10001:10001

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:14100/api/v1/health', timeout=5)"

CMD ["python", "-m", "uvicorn", "gateway.api_gateway.main:app", \
     "--host", "0.0.0.0", "--port", "14100", "--workers", "2"]
