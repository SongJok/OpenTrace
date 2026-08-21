# OpenTrace

**English** | [Simplified Chinese](README-EN.md)

[![CI](https://github.com/SongJok/OpenTrace/actions/workflows/ci.yml/badge.svg)](https://github.com/SongJok/OpenTrace/actions/workflows/ci.yml)
[![vNext contracts](https://github.com/SongJok/OpenTrace/actions/workflows/vnext-contract.yml/badge.svg)](https://github.com/SongJok/OpenTrace/actions/workflows/vnext-contract.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11–3.12](https://img.shields.io/badge/Python-3.11--3.12-3776AB.svg)](https://www.python.org/)

OpenTrace is a self-hosted enterprise AgentOS. Built around an OpenAI-compatible Responses
API, a recoverable Agent Loop, and durable PostgreSQL events, it gives users one focused
question experience backed by four governed runtime capabilities: Production Intelligence,
read-only DataAgent, Config Intelligence, and RAG. Enterprise-brain context, company Skills, and
personal memory remain scoped context rather than freely callable agents.

> **Project status: Controlled enterprise Beta.** The supported product path is ready for
> governed tenant pilots and is protected by product-wide Beta gates. This is not GA: production
> rollout still requires real Responses evaluation results, secret and network isolation,
> backup/recovery evidence, capacity planning, and an organization-level security review.

## Why OpenTrace

- **Joint reasoning over enterprise data and knowledge:** connect MySQL, Doris, ClickHouse, or
  PostgreSQL within a governed workspace and combine data with published knowledge and citations.
- **Production intelligence with evidence:** connect business assets to services, repositories,
  deployments, configuration, observability, data, and owners; conclusions pass deterministic
  evidence and critic gates before they are presented.
- **Durable execution instead of request-bound jobs:** the API only submits commands. Workers
  execute through an Outbox, Redis Streams, and database leases. Browser disconnects do not
  cancel work, and SSE streams can resume from a sequence number.
- **Governance by default:** tenant, workspace, user, and data-source boundaries are
  checked across the API, Agent runtime, and background jobs. Write and destructive tools pause
  at durable approval checkpoints.
- **Governed company understanding:** versioned company and department cognitive profiles bind
  the enterprise directory to governed knowledge spaces, so Responses understand authorized
  organizational context without turning employee chat into company facts.
- **Focused question workflow:** every question is routed through the same durable Responses
  path. RAG supplies citations, the enterprise brain supplies authorized company context, and
  DataAgent supplies validated read-only data answers, governed failure learning, and Golden Case release gates.
- **Observable, testable, and replaceable:** all model calls pass through the Model Gateway,
  while architecture boundaries, Responses, RAG, DataAgent, approvals, and scheduling are
  protected by contract tests.

## Product Workflow

Authenticated users land on `/chat`, the question page. The page is the only employee work
surface: ask a question and receive an
answer with RAG citations, enterprise-brain context, or a read-only DataAgent result. Supporting
pages are limited to personal data, databases, memory, tasks, Skills, and settings. Enterprise
brain, enterprise knowledge, knowledge quality, and permissions are administrator-only pages.

```text
Question page / enterprise channel
  `-- IntentPlan -> ContextAssembler -> Manager loop
       |-- Production: assets + governed connector evidence
       |-- Data: authorized database -> validated read-only SQL -> evidence
       |-- Config: policy + history + capacity + dry-run validation
       |-- RAG: reviewed knowledge with citations
       `-- Enterprise brain / company Skills / memory: authorized context
```

A typical workflow looks like this:

1. An administrator configures enterprise knowledge, company-brain profiles, permissions,
   authorized database sources, the Production Asset Graph, and disabled-by-default connectors.
2. A user opens `/chat` and asks a question within their authorized workspace scope.
3. The Manager loop chooses the smallest set among Production, Data, Config, and RAG;
   enterprise-brain, company-Skill, and personal-memory context is injected by the
   ContextAssembler and is never exposed as a freely callable agent.

## Core Architecture

```text
POST /api/v2/responses
  -> Validate identity, tenant, workspace, data source, and idempotency key
  -> Commit PostgreSQL Response / Item / Event / Outbox in one transaction
  -> Worker publishes Redis Streams messages and claims Responses with database leases
  -> IntentPlan -> ContextAssembler -> Manager model/tool loop
  -> Production / Data / Config / RAG plus authorized enterprise context
  -> Governed Connector Gateway -> MCP / Native / REST / RPC
  -> Evidence ledger -> fusion -> deterministic critic
  -> Persist output, events, model calls, and tool ledger in PostgreSQL
  -> Resume SSE by sequence_number
  -> Continue with summaries and memory learning
```

PostgreSQL is the source of truth for online execution. Redis is used only for delivery, wake-up,
and optional projections. The legacy `/api/v1/chat` and `/api/v1/tasks` endpoints are retired and
return `410 Gone`.

## Capabilities

| Area | Current capabilities |
| --- | --- |
| Responses | Durable responses, streaming events, retry, cancellation, approval, reconnect, and conversation branches |
| Agent Loop | IntentPlan, minimum-capability selection, tool loop, expert agents, evidence synthesis, and step limits |
| Enterprise databases | MySQL, Doris, ClickHouse, and PostgreSQL; connection tests, schemas, semantic mappings, governed SQL assets, and confirmed read-only execution |
| DataAgent | DataAgent drafts, asset grounding, stable candidates, metric/entity/time/join reasoning, validation, confirmation, and result interpretation |
| Production Intelligence | Scoped asset graph, observability/code/deployment/business evidence, production diagnosis, impact analysis, and evidence critic |
| Config Intelligence | Versioned policy, snapshots, Schema/reference/business/history/capacity/conflict checks, and governed dry-run |
| Enterprise connectors | Disabled-by-default MCP/Native/REST/RPC catalog, operation allowlists, secret references, policy, sanitization, timeout, audit, and evidence persistence |
| Enterprise Knowledge | Company/department/role/workspace/personal spaces, source ACL sync, review publishing, validity, classification, governed retrieval, graphs, and citations |
| Governance | Multi-tenant/workspace boundaries, resource permissions, durable approvals, quotas, and policy interfaces |
| User support | Personal profile, databases, memory, tasks, Skills, and settings |
| Memory | Conversation summaries, user and conversation memory, memory governance, and feedback learning |
| Skills and tools | Typed tools, SkillHub, and local Skill management; dynamic execution is disabled by default |
| Observability | Structured logging, OpenTelemetry, Prometheus, Jaeger, and runtime health endpoints |
| Frontend | Focused question page plus React, TypeScript, and Vite pages for personal data, databases, memory, tasks, Skills, settings, and administrator governance |

## Technology Stack

- Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, and Alembic
- PostgreSQL 16 with pgvector, plus Redis 7
- OpenAI-compatible Responses and model adapters; examples default to Qwen and DashScope
- React 18, TypeScript, Vite, Zustand, and Tailwind CSS
- Docker Compose, with optional Prometheus and Jaeger profiles

## Quick Start

### Prerequisites

- Docker 24+
- Docker Compose 2.20+
- Node.js 20.19+ and npm 10+ for the frontend
- Python 3.11 or 3.12 for local development and tests

### 1. Prepare the configuration

```bash
git clone https://github.com/SongJok/OpenTrace.git
cd OpenTrace
cp .env.example .env
```

`.env.example` contains no real credentials. Configure the shared free model source shown to users:

```env
FREE_LLM_MINSHORT_BASE_URL=https://coding-api-3671.underpinetree.com
FREE_LLM_MINSHORT_API_KEY=your-shared-free-model-key
FREE_LLM_MODEL1=glm-5.2-free
FREE_LLM_MODEL2=deepseek-v4-pro-free
```

Users may also add their own OpenAI-compatible model from Settings. Its API Key is encrypted with
`DATA_SECRET_KEY` and scoped to the current user, tenant, and workspace. Specialized internal or
multimodal roles can still use the corresponding `DEFAULT_LLM_*` variables from `.env.example`.

Embedding and reranking may share `DASHSCOPE_API_KEY` or use separate keys. Staging and production
deployments must set independent `APP_SECRET_KEY`, `JWT_SECRET`, and `DATA_SECRET_KEY` values and
replace the development database and seed-user passwords from the template.

### 2. Start the backend

```bash
bash start.sh
```

On the first run, OpenTrace builds the shared API/Worker image, starts PostgreSQL, Redis, the API,
and the Agent Worker, applies Alembic migrations, and creates the development seed account. Later
starts reuse the image when its source fingerprint is unchanged.

Common options:

```bash
bash start.sh --build               # Force an incremental image build
bash start.sh --rebuild             # Rebuild without cache for cache troubleshooting
bash start.sh --with-observability  # Enable Prometheus and Jaeger
bash start.sh --verify              # Run Docker smoke checks after startup
```

Python dependencies are installed with `uv`, BuildKit download caching, retries, and locked hashes.
For mainland China servers the template uses the Aliyun mirror first and official PyPI as fallback;
`start.sh` prints the effective sources so an older `.env` override is immediately visible.

Verify the services:

```bash
curl http://127.0.0.1:14100/api/v1/health
curl http://127.0.0.1:14100/api/v1/health/deps
```

### 3. Open the production frontend

`bash start.sh` builds the React app and starts the Nginx frontend container automatically.
Open <http://localhost:14108>. API requests and SSE streams are reverse-proxied through the same
origin; Swagger is available at <http://localhost:14100/docs>.

For local HMR development only, stop the Compose `frontend` service first, then run:

```bash
cd frontend
npm ci
npm run dev
```

## Service Ports

| Service | Host port | Container port |
| --- | ---: | ---: |
| API / Swagger | `14100` | `14100` |
| Production frontend (Nginx) | `14108` | `14108` |
| PostgreSQL | `5432` | `5432` |
| Redis | `6380` | `6379` |
| Prometheus, optional | `14190` | `9090` |
| Jaeger UI, optional | `14186` | `16686` |
| OTLP gRPC, optional | `4317` | `4317` |

The API port is controlled by `APP_PORT=14100`. `GATEWAY_PORT` must match it; inconsistent values
cause staging and production startup to fail fast.

## Database Integration

| Type | Driver / protocol | Default port | Notes |
| --- | --- | ---: | --- |
| MySQL | `aiomysql` | `3306` | Read-only session settings, schema synchronization, and DataAgent |
| Doris | MySQL protocol / `aiomysql` | `9030` | Doris dialect with a compatible read-only execution strategy |
| ClickHouse | `clickhouse-sqlalchemy` + `asynch` | `9000` | Schema synchronization through ClickHouse system tables |
| PostgreSQL | `asyncpg` | `5432` | PostgreSQL dialect and read-only transactions |

Create a least-privilege, read-only account for every production data source. OpenTrace also uses
SQL AST allowlists, SQL hashes, Schema fingerprints, result row limits, execution timeouts, and
workspace/ACL validation. Uploaded ETL/DDL/DML is retained only for lineage; it is never eligible for
interactive execution. These application-level controls do not replace database permissions.

## Configuration and Security

Configuration precedence is: environment variables, then `.env`, then defaults in
`infra/config/settings.py`.

- `.env.example`: sanitized, committable configuration template.
- `docs/ENV_PROFILES.md`: recommended development, staging, and production profiles.
- `docs/CONFIG_TRUTH.md`: source of truth for ports, URLs, and configuration.
- `docs/FEATURE_FLAG_REGISTRY.md`: governed kernel feature flags.
- `SECURITY.md`: vulnerability reporting and deployment security requirements.

Run the public-release check before committing:

```bash
python scripts/check_public_release.py
```

The check rejects tracked `.env` files, private keys, local runtime artifacts, duplicate
configuration entries, sensitive template values, and runtime dependency drift.

## API Overview

### `/api/v2`: current Agent product path

- `POST /api/v2/responses`
- Response queries, event streams, retry, cancellation, and approval
- Conversations, Assistant Profiles, and Goals
- Scheduled Tasks, Active Alerts, and Notifications
- Resource Permissions, Memories, and Personalization
- Production assets, graph import, enterprise connectors, capability policy, configuration
  policies/snapshots/validation, and the administrator Production Intelligence workbench

### `/api/v1`: business resources and compatibility APIs

- Auth, Health, Documents, Knowledge, Databases, and Data Query
- Metrics, Table Relationships, and Analytical Skills
- Connectors, Skills, Audit, Rules, Admin, and Sandbox

Swagger is the authoritative, up-to-date API definition.

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
bash scripts/bootstrap_dev.sh
```

When PostgreSQL and Redis run in Docker while the API runs on the host, override the container
network hostnames:

```bash
DATABASE_URL=postgresql://postgres:opentrace-dev@127.0.0.1:5432/opentrace_v2 \
TOKEN_DB_URL=postgresql://postgres:opentrace-dev@127.0.0.1:5432/opentrace_v2 \
REDIS_URL=redis://127.0.0.1:6380/10 \
python -m uvicorn gateway.api_gateway.main:app --host 0.0.0.0 --port 14100 --reload
```

Database migrations:

```bash
bash scripts/migrate.sh
bash scripts/verify_migration_idempotent.sh
```

## Testing

```bash
# Backend
python -m pytest -q
bash scripts/check_import_boundaries.sh
bash scripts/run_vnext_final_tests.sh
bash scripts/run_enterprise_contract_tests.sh
bash scripts/run_product_beta_gate.sh --contract

# Check the Python files changed by your patch; replace these example paths.
ruff check path/to/changed.py
black --check path/to/changed.py

# Frontend
cd frontend
npm test
npm run build
```

Additional checks for a running Docker stack:

```bash
bash scripts/verify_docker.sh
bash scripts/verify_all_docker.sh
bash scripts/preflight_release.sh --full
```

## Repository Layout

```text
gateway/          FastAPI application and API routers
infra/            Configuration, databases, Responses, messaging, security, and observability
kernel/           Manager Agent Loop, context assembly, runtime, and data cognition
agents/           Online DataAgent/RAG experts, offline compatibility agents, and Worker
connectors/       Governed MCP/Native connector contracts, gateway, registry, and SDK
knowledge/        Enterprise knowledge orchestration and retrieval
memory/           Memory infrastructure and governance
model/            Model Gateway, provider adapters, embeddings, and reranking
execution/        SQL, DAG, workflow, and sandbox execution
tools/            Typed tool registry and built-in tools
skills/           Skill runtime, catalog, and installation policies
governance/       Constitution, approvals, and governance policies
frontend/         React and TypeScript user interface
alembic/          PostgreSQL migrations
docs/             Architecture, catalog, configuration, and runbooks
scripts/          Development, testing, migration, release, and operations scripts
tests/            Unit, integration, and architecture contract tests
```

## Documentation

- [Product vision: enterprise organization OS](docs/PRODUCT_VISION.md)
- [Production Intelligence architecture](docs/architecture/production_intelligence_platform.md)
- [Enterprise Connector development](docs/CONNECTOR_DEVELOPMENT.md)
- [Production Intelligence threat model](docs/security/production_intelligence_threat_model.md)
- [Production Intelligence rollout](docs/runbooks/production_intelligence_rollout.md)
- [Enterprise organization OS architecture](docs/architecture/enterprise_organization_os.md)
- [Responses enterprise Beta runbook](docs/runbooks/responses_enterprise_beta.md)
- [Product-wide controlled Beta readiness](docs/BETA_READINESS.md)
- [Architecture overview](docs/architecture_overview.md)
- [Responses cutover and rollback](docs/runbooks/chatgpt_cutover.md)
- [DataAgent](docs/catalog/data_agent.md)
- [RAG retrieval](docs/catalog/rag_retrieval.md)
- [Company Skills](docs/catalog/company_skills.md)
- [Agent Runtime](docs/catalog/agent_runtime.md)
- [Configuration truth](docs/CONFIG_TRUTH.md)
- [Environment profiles](docs/ENV_PROFILES.md)
- [Capability maturity](docs/CAPABILITY_MATURITY.md)

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before
contributing. Report security issues privately according to [SECURITY.md](SECURITY.md), not in a
public issue.

## License

OpenTrace is released under the [MIT License](LICENSE).
