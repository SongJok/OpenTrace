ARG PYTHON_BASE_IMAGE=python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

WORKDIR /app

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG PIP_EXTRA_INDEX_URL=https://pypi.org/simple
ARG UV_VERSION=0.8.24
ARG UV_HTTP_TIMEOUT=120
ARG UV_HTTP_RETRIES=5

COPY requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cache/uv \
    PIP_INDEX_URL="${PIP_INDEX_URL}" \
    PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL}" \
    pip install --prefer-binary --disable-pip-version-check "uv==${UV_VERSION}" \
    && UV_INDEX_URL="${PIP_INDEX_URL}" \
    UV_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL}" \
    UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT}" \
    UV_HTTP_RETRIES="${UV_HTTP_RETRIES}" \
    UV_LINK_MODE=copy \
    uv pip install --system --require-hashes -r requirements.lock

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
