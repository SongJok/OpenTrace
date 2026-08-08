# OpenTrace

**English** | [Simplified Chinese](README-EN.md)

[![CI](https://github.com/SongJok/OpenTrace/actions/workflows/ci.yml/badge.svg)](https://github.com/SongJok/OpenTrace/actions/workflows/ci.yml)
[![vNext contracts](https://github.com/SongJok/OpenTrace/actions/workflows/vnext-contract.yml/badge.svg)](https://github.com/SongJok/OpenTrace/actions/workflows/vnext-contract.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11–3.12](https://img.shields.io/badge/Python-3.11--3.12-3776AB.svg)](https://www.python.org/)

OpenTrace is a self-hosted enterprise AgentOS. Built around an OpenAI-compatible Responses
API, a recoverable Agent Loop, and durable PostgreSQL events, it brings enterprise databases,
knowledge bases, approval governance, proactive alerts, conversations, memory, goals, and
scheduled tasks into one coherent product workflow. The enterprise AI workbench turns those
durable capabilities into one actionable employee home.

> **Project status: Controlled enterprise Beta.** The supported product path is ready for
> governed tenant pilots and is protected by product-wide Beta gates. This is not GA: production
> rollout still requires real Responses evaluation results, secret and network isolation,
> backup/recovery evidence, capacity planning, and an organization-level security review.

## Why OpenTrace

- **Joint reasoning over enterprise data and knowledge:** bind MySQL, Doris, ClickHouse, or
  PostgreSQL to a Project and combine governed data with published knowledge and citations.
- **Durable execution instead of request-bound jobs:** the API only submits commands. Workers
  execute through an Outbox, Redis Streams, and database leases. Browser disconnects do not
  cancel work, and SSE streams can resume from a sequence number.
- **Governance by default:** tenant, workspace, user, Project, and data-source boundaries are
  checked across the API, Agent runtime, and background jobs. Write and destructive tools pause
  at durable approval checkpoints.
- **Governed company understanding:** versioned company and department cognitive profiles bind
  the enterprise directory to governed knowledge spaces, so Responses understand authorized
  organizational context without turning employee chat into company facts.
- **From data questions to proactive alerts:** DataAgent and Text2SQL generate governed read-only
  SQL drafts grounded by reviewed SQL assets. Interactive queries execute only after the user
  selects a persisted candidate; alerts retain their trusted background execution contract.
- **Observable, testable, and replaceable:** all model calls pass through the Model Gateway,
  while architecture boundaries, Responses, RAG, DataAgent, approvals, and scheduling are
  protected by contract tests.

## Product Workflow

Authenticated users land on `/work`, the enterprise AI workbench. It aggregates current
Responses, Goals, approvals, alerts, governed knowledge, and authorized data sources without
creating a second execution plane. See
[Enterprise AI workbench architecture](docs/architecture/enterprise_ai_workbench.md).

```text
Enterprise AI Workbench
  `-- Today pulse / Project portfolio / attention queue / durable work / capability launchpad
       `-- Project
            |-- Enterprise databases: MySQL / Doris / ClickHouse / PostgreSQL
            |     `-- Connection test -> Schema sync -> Semantic layer -> DataAgent / Text2SQL
            |-- Enterprise knowledge: Documents -> Compile -> Review/Publish -> RAG citations
            |-- Approval governance: Tenant/Workspace/Project ACL -> Write approval -> Audit events
            `-- Proactive alerts: Scheduled query -> Deterministic threshold -> Trigger/Recover -> Evidence
```

A typical workflow looks like this:

1. Connect and verify an enterprise data source from the Databases page. OpenTrace synchronizes
   its schema automatically.
2. Create a Project, bind the data sources that may be queried, and upload policies, metric
   definitions, or business documents.
3. Select the Project and data source in Chat, then ask questions that combine operational data
   with governed knowledge.
4. Open `/knowledge-base` to search authorized company knowledge or contribute to a space; use `/knowledge` for compiler and governance operations.
5. Ask the Agent to create an alert rule. The write operation enters approval first, and the Worker runs it continuously after approval.

## Core Architecture

```text
POST /api/v2/responses
  -> Validate identity, tenant, Project, data source, and idempotency key
  -> Commit PostgreSQL Response / Item / Event / Outbox in one transaction
  -> Worker publishes Redis Streams messages and claims Responses with database leases
  -> IntentPlan -> ContextAssembler -> Manager model/tool loop
  -> Typed tools / expert agents / RAG / DataAgent
  -> Write or destructive tool -> Durable approval pause point
  -> Persist output, events, model calls, and tool ledger in PostgreSQL
  -> Resume SSE by sequence_number
  -> Continue with summaries, memory learning, Goals, Tasks, and Alerts
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
| DataAgent | Text2SQL drafts, asset grounding, stable candidates, metric/entity/time/join reasoning, validation, confirmation, and result interpretation |
| Enterprise Knowledge | Company/department/role/project/personal spaces, source ACL sync, review publishing, validity, classification, governed retrieval, graphs, and citations |
| Governance | Multi-tenant/workspace boundaries, enterprise directory sync, resource permissions, durable approvals, audit, quotas, and policy interfaces |
| Automation | Goals, scheduled tasks, proactive data alerts, notifications, retries, and recovery events |
| Memory | Conversation summaries, user and Project memory, memory governance, and feedback learning |
| Skills and tools | Typed tools, SkillHub, and local Skill management; dynamic execution is disabled by default |
| Observability | Structured logging, OpenTelemetry, Prometheus, Jaeger, and runtime health endpoints |
| Frontend | Employee AI workbench and administrator operations center, plus React, TypeScript, and Vite interfaces for chat, data, knowledge, approvals, tasks, and alerts |

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
| MySQL | `aiomysql` | `3306` | Read-only session settings, schema synchronization, and Text2SQL |
| Doris | MySQL protocol / `aiomysql` | `9030` | Doris dialect with a compatible read-only execution strategy |
| ClickHouse | `clickhouse-sqlalchemy` + `asynch` | `9000` | Schema synchronization through ClickHouse system tables |
| PostgreSQL | `asyncpg` | `5432` | PostgreSQL dialect and read-only transactions |

Create a least-privilege, read-only account for every production data source. OpenTrace also uses
SQL AST allowlists, SQL hashes, Schema fingerprints, result row limits, execution timeouts, and
Project/ACL validation. Uploaded ETL/DDL/DML is retained only for lineage; it is never eligible for
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
- Conversations, Projects, Assistant Profiles, and Goals
- Scheduled Tasks, Active Alerts, and Notifications
- Resource Permissions, Memories, and Personalization

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
agents/           Expert agents, DataAgent V2, RAG Agent, and Worker
knowledge/        Enterprise knowledge orchestration and retrieval
memory/           Memory infrastructure and governance
model/            Model Gateway, provider adapters, embeddings, and reranking
execution/        SQL, DAG, workflow, and sandbox execution
tools/            Typed tool registry and built-in tools
skills/           Skill runtime, catalog, and installation policies
connectors/       Connector registry, SDK, and built-in connectors
governance/       Constitution, approvals, and governance policies
frontend/         React and TypeScript user interface
alembic/          PostgreSQL migrations
docs/             Architecture, catalog, configuration, and runbooks
scripts/          Development, testing, migration, release, and operations scripts
tests/            Unit, integration, and architecture contract tests
```

## Documentation

- [Product vision: enterprise organization OS](docs/PRODUCT_VISION.md)
- [Enterprise organization OS architecture](docs/architecture/enterprise_organization_os.md)
- [Responses enterprise Beta runbook](docs/runbooks/responses_enterprise_beta.md)
- [Product-wide controlled Beta readiness](docs/BETA_READINESS.md)
- [Architecture overview](docs/architecture_overview.md)
- [Enterprise AI workbench](docs/architecture/enterprise_ai_workbench.md)
- [Enterprise identity and operations](docs/architecture/enterprise_identity_and_operations.md)
- [Responses cutover and rollback](docs/runbooks/chatgpt_cutover.md)
- [DataAgent](docs/catalog/data_agent.md)
- [RAG retrieval](docs/catalog/rag_retrieval.md)
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
