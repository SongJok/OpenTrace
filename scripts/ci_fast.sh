#!/usr/bin/env bash
# PR <12 分钟快速门禁；本地与 CI 使用同一入口。
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:---all}"
PYTHON_BIN="${PYTHON_BIN:-python}"
QUALITY_PATHS=(
  gateway/api_gateway/routers/responses.py
  gateway/api_gateway/routers/auth.py
  connectors/security.py
  execution/data/db_router.py
  execution/data/sql_executor.py
  infra/responses
  kernel/agent_loop
  agents/bootstrap.py
  infra/config
  scripts/check_architecture_manifest.py
  scripts/check_migration_policy.py
  scripts/create_migration.py
  scripts/freeze_migration.py
  scripts/generate_feature_flag_docs.py
  tests/test_p0_engineering_baseline.py
)

backend_gate() {
  "$PYTHON_BIN" -m uv lock --check
  "$PYTHON_BIN" -m black --check "${QUALITY_PATHS[@]}"
  "$PYTHON_BIN" -m ruff check "${QUALITY_PATHS[@]}"
  "$PYTHON_BIN" -m mypy --follow-imports=skip \
    infra/config agents/bootstrap.py \
    scripts/check_architecture_manifest.py \
    scripts/check_migration_policy.py scripts/create_migration.py scripts/freeze_migration.py

  local env_before docs_before env_after docs_after
  env_before="$(shasum -a 256 .env.example)"
  docs_before="$(shasum -a 256 docs/FEATURE_FLAG_REGISTRY.md)"
  "$PYTHON_BIN" scripts/sync_env_example_to_docs.py
  "$PYTHON_BIN" scripts/generate_feature_flag_docs.py
  env_after="$(shasum -a 256 .env.example)"
  docs_after="$(shasum -a 256 docs/FEATURE_FLAG_REGISTRY.md)"
  test "$env_before" = "$env_after"
  test "$docs_before" = "$docs_after"

  "$PYTHON_BIN" scripts/check_architecture_manifest.py
  "$PYTHON_BIN" scripts/check_migration_policy.py
  bash scripts/check_import_boundaries.sh
  "$PYTHON_BIN" -m pytest -q --tb=short \
    tests/test_p0_engineering_baseline.py \
    tests/test_config_truth_contract.py \
    tests/test_alembic_single_head_contract.py \
    tests/test_responses_contract.py \
    tests/test_kernel_agent_loop.py \
    tests/test_rag_agent_contract.py \
    tests/test_data_agent_v2_supervisor_contract.py \
    tests/test_scheduler_v2.py
}

frontend_gate() {
  (cd frontend && npm ci && npm test -- --run && npm run build)
}

case "$MODE" in
  --backend) backend_gate ;;
  --frontend) frontend_gate ;;
  --all) backend_gate; frontend_gate ;;
  *) echo "usage: $0 [--backend|--frontend|--all]" >&2; exit 2 ;;
esac
