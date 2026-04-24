ARG PYTHON_BASE_IMAGE=python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

RUN set -eux; \
    apt-get update -o Acquire::Retries=5 -o Acquire::http::Timeout=30; \
    apt-get install -y --no-install-recommends curl build-essential libpq-dev; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 14100

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:14100/api/v1/health || exit 1

CMD ["python", "-m", "uvicorn", "gateway.api_gateway.main:app", \
     "--host", "0.0.0.0", "--port", "14100", "--workers", "2"]
