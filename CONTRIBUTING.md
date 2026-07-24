# Contributing to OpenTrace

Thank you for contributing. OpenTrace is a full-stack AgentOS project with strict runtime,
tenant-isolation, approval, and persistence contracts.

## Development setup

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
bash scripts/bootstrap_dev.sh

cd frontend
npm ci
```

PostgreSQL and Redis are most easily started through Docker Compose. See `README.md` for the
complete startup flow and port map.

## Pull requests

1. Keep changes focused and explain the user-visible outcome.
2. Add or update contract tests for behavior changes.
3. Preserve user, tenant, workspace, and Project boundaries on every resource query.
4. Do not execute models or tools inside the API process; durable Responses run in Worker.
5. Route write/destructive tools through persisted approval and idempotency records.
6. Update `.env.example` and configuration documentation when adding settings.
7. Do not commit secrets, local state, generated artifacts, or dependency directories.

## Required checks

```bash
python -m pytest -q
bash scripts/check_import_boundaries.sh

# Replace these paths with the Python files changed by the pull request.
ruff check path/to/changed.py
black --check path/to/changed.py

cd frontend
npm test
npm run build
```

For release-sensitive changes also run:

```bash
bash scripts/run_vnext_final_tests.sh
bash scripts/run_enterprise_contract_tests.sh
python scripts/check_public_release.py
```

By contributing, you agree that your contribution is licensed under the MIT License.
