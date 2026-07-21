ARG PYTHON_BASE_IMAGE=python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

WORKDIR /app

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG PIP_EXTRA_INDEX_URL=

COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    PIP_INDEX_URL="${PIP_INDEX_URL}" \
    PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL}" \
    pip install --prefer-binary --disable-pip-version-check -r requirements.txt

COPY . .

ARG OPENTRACE_BUILD_FINGERPRINT=unknown
LABEL org.opentrace.build-fingerprint="${OPENTRACE_BUILD_FINGERPRINT}"

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=120

EXPOSE 14100

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:14100/api/v1/health', timeout=5)"

CMD ["python", "-m", "uvicorn", "gateway.api_gateway.main:app", \
     "--host", "0.0.0.0", "--port", "14100", "--workers", "2"]
