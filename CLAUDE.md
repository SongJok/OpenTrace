# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

OpenTrace is a cognitive kernel-centric agent system supporting conversational QA (sync/streaming), tool invocation (web/time/weather/code), reasoning chain visualization, and V4 architecture: Plan + Dispatcher + Agent Cluster + Fusion + Critic. The system uses Docker for unified deployment.

**Language / Runtime:** Python 3.11+, FastAPI, React/Vite frontend
**Package manager:** pip (editable install: `pip install -e ".[dev]"`)

## Common Commands

### Running the Service

- Start all services (with migration checks): `bash start.sh`
- Stop services: `bash stop.sh`
- Force restart (recommended): `bash restart.sh`
- Start with observability: `bash start.sh --with-observability`
- Start with verification: `bash start.sh --verify`
- View API logs: `bash scripts/docker_logs.sh api`
- View agent-worker logs: `bash scripts/docker_logs.sh agent-worker`
- Full reset (including volumes): `bash stop.sh --volumes && bash start.sh`

**Important — Docker code deployment:** The Dockerfile uses `COPY . .` (not volume mounts), so source code is baked into the image at build time. Both `start.sh` and `restart.sh` run `docker compose up -d --build` which rebuilds images. However, Docker's layer cache may skip rebuilding the `COPY . .` step. When source changes don't seem to take effect in the running container, force a full rebuild:

```bash
docker compose build --no-cache api agent-worker && bash restart.sh
```

### Verification Scripts

- Run all verification (local): `bash scripts/verify_all.sh`
- Run all verification (Docker): `bash scripts/verify_all_docker.sh`
- Verify agent cluster (V4 + RAG + bus): `bash scripts/verify_agent_cluster.sh`
- Verify agent bus end-to-end: `bash scripts/verify_agent_bus_e2e.sh`
- Verify migration idempotency: `bash scripts/verify_migration_idempotent.sh`
- Verify error envelope: `bash scripts/verify_error_envelope.sh`
- Verify E2E flow (login → chat → documents): `bash scripts/verify_e2e.sh`

### Testing

- Run unit/contract tests: `pytest` (default test paths in `tests/`)
- Run a specific test: `pytest tests/path/to/test.py::test_function`
- Key contract test modules:
  - `tests/test_orchestrator_v4_contract.py` – V4 orchestration
  - `tests/test_rag_agent_contract.py` – RAG agent
  - `tests/test_agent_bus_e2e_contract.py` – agent bus routing
  - `tests/test_databases_api_contract.py` – data source management
  - `tests/test_text2sql_validator_contract.py` – SQL validation
  - `tests/test_cognition_self_model_contract.py` – cognitive models

### Maintenance

- Apply baseline schema: `bash scripts/apply_provided_schema_to_docker.sh`
- Migrate local PostgreSQL to Docker: `bash scripts/migrate_local_pg_to_docker.sh`
- Clean session data: `bash scripts/clean_session.sh`
- Pre‑flight release checks: `bash scripts/preflight_release.sh`
- Check migration history: `docker compose exec -T api alembic history --verbose`
- Upgrade migrations: `docker compose exec -T api alembic upgrade head`

### Database Migrations

Migrations live in `alembic/versions/`. Alembic is configured in `alembic.ini` and `alembic/env.py`.
All migrations are expected to be idempotent — verify with `bash scripts/verify_migration_idempotent.sh`.
The baseline schema is also available as `scripts/sql/provided_schema.sql` for reference.

## Docker Services

The `docker-compose.yml` defines the following core services:

- `postgres` – PostgreSQL with pgvector (port 5432)
- `redis` – Redis (port 6380 on host, 6379 in container)
- `api` – FastAPI gateway (port 14100)
- `agent-worker` – Agent worker consuming from Redis bus
- `prometheus` – Metrics scraping (port 9090)
- `jaeger` – Distributed tracing (port 16686)

All services are started together via `start.sh`. Use `docker compose ps` to see status.

## Frontend Development

The frontend is a React/Vite application in `frontend/`. For local development:

- Install dependencies: `cd frontend && npm install`
- Run dev server: `npm run dev` (serves on `http://localhost:14108`)
- Build for production: `npm run build`
- Run frontend tests: `npm run test` (uses Vitest)

The dev server proxies API requests to `http://localhost:14100`.

## Architecture

### High‑Level Layers

1. **Frontend** (React/Vite) – User interface at `http://localhost:14108`
2. **Gateway** (FastAPI) – API entry point at `http://localhost:14100`, handles auth, routing, SSE, health checks.
   - `gateway/api_gateway/` – REST API routes (chat, health, documents, auth).
   - `gateway/cognitive_gateway/` – Cognitive-aware gateway endpoints.
3. **Cognitive Kernel** (`kernel/`) – Core orchestration brain:
   - `cognitive_kernel.py`: unified `run`/`stream` entry, routes to V4 orchestrator.
   - `orchestrator_v4.py`: main orchestrator implementing **Plan + Dispatcher + Agent Cluster**.
   - `plan_agent.py` / `dag_plan.py` / `dag_scheduler.py`: decompose queries into DAG subtasks with parallel scheduling.
   - `dispatcher.py`: concurrent scheduling, timeout, degradation.
   - `context_builder.py` / `context_pipeline.py`: query context assembly pipeline.
   - `intent_engine/`: user intent recognition and routing.
   - `meta_cognition/` / `epistemology/`: self-assessment and knowledge confidence.
   - `fusion_engine/` and `critic_engine/`: merge results and critique.
   - `adaptive_profiles.py`: dynamic quality/speed profile switching.
   - `cognition/` / `data_cognition/`: entity recognition and canonical name resolution.
   - `identity/` — System identity & persona enforcement:
     - `system_identity.py`: `SYSTEM_IDENTITY` prompt template, `CANONICAL_IDENTITY_RESPONSE` (fallback), `is_identity_user_query()`, `enforce_identity_output()` (post-process filter), `build_identity_llm_messages()` (context-aware identity prompt builder).
     - L0 identity queries ("你是谁") route through `orchestrator_v4._handle_identity_query()` → `LLMRole.IDENTITY` (MinShort 0.6B) → response cached in WorkingMemory with turn-sequence freshness check (expires after 5 turns).
     - Feature flag: `kernel_identity_llm_enabled` (True=LLM动态生成, False=回退固定答案).
4. **Agent Cluster** (`agents/`) – Parallel execution units:
   - `data_agent.py`: structured data queries (Text2SQL).
   - `web_agent.py`: web search (Serper API).
   - `rag_agent.py`: document + memory retrieval (pgvector, dynamic score threshold).
   - `tool_agent.py`: generic tool invocation (time/weather/code).
   - `skills_agent.py`: specialized skill invocation.
   - `worker.py`: consumes from Redis bus (stream/pubsub modes).
   - `registry.py`: agent registration and discovery.
5. **Model Gateway** (`model/`) — Abstracts LLM calls with role‑based routing. Roles form a capability hierarchy:

   | Role | Typical Model | Purpose |
   |------|--------------|---------|
   | `QUERY` | qwen3.6-plus | Primary reasoning & answer generation |
   | `PLANNING` | qwen3.6-plus | Task decomposition & plan generation |
   | `COMPRESS` | qwen3.5-27b | Context compression & memory summarization |
   | `ROUTER` | qwen3-1.7b (JuniorShort) | L1 intent classification |
   | `FAST` | qwen3-8b (MiddleShort) | Simple/FAQ direct answers |
   | `CHEAP_CRITIC` | qwen3-14b (SeniorShort) | Lightweight output critique |
   | `KNOWLEDGE` | qwen3-14b (SeniorShort) | Knowledge Q&A |
   | `IDENTITY` | qwen3-0.6b (MinShort) | Personalized identity responses (L0) |
   | `VISION` | qwen3.6-vl-plus | Image/chart interpretation |

   - `model/model_gateway/gateway.py`: role configs, circuit breaker, offline fallback, `merge_system_identity`.
   - `model/llm_adapter/`: provider adapters (DashScope, OpenAI-compatible).
6. **Memory** (`memory/`) – Multi‑layer memory (working, semantic, episodic, procedural).
7. **Execution Plane** (`execution/`) – Tool routing, data query, DAG/workflow engines.
8. **Infrastructure** (`infra/`) – Config, storage, observability, error handling, guards.

### Data & Caching

- **PostgreSQL** – Business persistence: users, sessions, documents, memories, tasks, audit, data assets.
- **Redis** – Checkpoint, cache, session, rate‑limit, pub/sub, stream (agent bus).

### Key Configuration

- Orchestrator version: `KERNEL_ORCHESTRATOR_VERSION=v4` (default)
- Agent toggles: `KERNEL_AGENT_ENABLED=true`, `KERNEL_AGENT_DATA_ENABLED=true`, etc.
- Environment variables are defined in `.env.example` — copy to `.env` before starting.
- Key LLM config vars: `DEFAULT_LLM_QUERY_MODEL`, `DEFAULT_LLM_PLANING_MODEL`, `DEFAULT_LLM_COMPRESS_MODEL` (each with `_PROVIDER`, `_BASE_URL`, `_API_KEY` suffixes).
- Embedding: `EMBEDDING_PROVIDER` (default `hash`), `EMBEDDING_DIMS`, `EMBEDDING_BASE_URL`.
- Web search: `SERPER_API_KEY` required for `web_agent.py`.
- Draft answering: `KERNEL_ANSWER_DRAFT_CONFIDENCE_THRESHOLD` (default 0.75), `KERNEL_ANSWER_DRAFT_MAX_CHARS` (default 220).
- RAG: `RAG_MIN_SCORE` (default 0.25, dynamically adjusted in code).
- Frontend: `VITE_API_URL` and `VITE_WS_URL` in `.env` must point to the API gateway.

### Feature Flags (selected)

All flags are defined in `infra/config/settings.py` and configurable via `.env`. Key flags beyond the basic agent toggles:

- `KERNEL_IDENTITY_LLM_ENABLED` (default `True`) — Use LLM for dynamic identity responses instead of fixed canned text.
- `KERNEL_V5_ROUTING_ENABLED` — Enable V5 routing tier (L0 Rule Router + L1 TinyRouter + semantic cache). Currently stubs.
- `KERNEL_SEMANTIC_CACHE_ENABLED` — Enable semantic (vector-based) answer cache. Currently a stub.
- `KERNEL_ADAPTIVE_MODE_ENABLED` — Enable dynamic quality/speed profile switching based on query complexity.
- `KERNEL_PLAN_MEMORY_ENABLED` / `KERNEL_PLAN_MEMORY_WINDOW` — Cache and reuse successful execution plans.
- `KERNEL_MEMORY_CONTEXT_ENABLED` — Enable memory context injection into LLM prompts.
- `KERNEL_CONTEXT_COMPOSER_ENABLED` — Enable V5 structured context assembly. Currently a stub.
- `KERNEL_USER_PROFILING_ENABLED` — Enable user preference-based style hints.

## Development Notes

- The main chat entry point is `gateway/api_gateway/routers/chat.py` – handles sync/streaming, permissions, data‑source context.
- V4 is the stable default; legacy v1‑v3 are kept for historical reference and compatibility tests.
- Agent Bus supports two modes: `pubsub` and `stream` (consumer‑group + ack + pending reclaim).
- All SQL queries are read‑only and bound to a `data_source_id` with post‑processing validation.
- Health endpoints:
  - `GET /api/v1/health` – basic liveness
  - `GET /api/v1/health/deps` – dependency health (database, Redis, agent worker, bus, orchestrator)
  - `GET /api/v1/health/runtime` – runtime info (orchestrator version, annotation switches, lexicon size)
- Default local development account: `songts@tuwan.com` / `123456`
- Code quality: run `black .` to format, `ruff check .` to lint, `mypy .` for type checking (config in `pyproject.toml`).
- Pre‑commit hooks can be installed via `pre‑commit install`.

## Further Reading

- `README.md` – Quick start and high‑level overview
- `scripts/work_script.md` – Detailed script usage
- `.env.example` – Full environment variable catalog (~150 vars) including all feature flags