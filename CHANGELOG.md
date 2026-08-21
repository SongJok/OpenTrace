# Changelog

All notable changes to OpenTrace will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses semantic versioning once stable release tags are published.

## [Unreleased]

### Added

- Durable Responses API and resumable Agent Loop.
- Workspace-scoped enterprise database, knowledge, approval, and active-alert workflow.
- MySQL, Doris, ClickHouse, and PostgreSQL data-source support.
- Open-source release documentation and public-release checks.
- Closed the governed chat DataAgent loop from trusted draft generation through candidate
  selection, durable approval, verified execution, evidence projection, and controlled learning.
- Added durable four-source intent contracts for memory, company context, RAG, and DataAgent,
  including freshness, evidence requirements, and governed data lifecycle stages.
- Added the Production Intelligence control plane: scoped asset graph and atomic imports,
  governed MCP/Native connector gateway, Production and Config agents, durable production-action
  approvals, standardized evidence/critic output, configuration validation, and an administrator
  workbench.
- Added a Native Connector SDK and a real Prometheus HTTP API adapter, an eight-scenario production evaluation dataset,
  connector development guide, threat model, and controlled rollout runbook.
- Added a ten-scenario Production Intelligence adversarial evaluation dataset covering isolation,
  prompt injection, evidence binding, SSRF, approval integrity, reconciliation, and cursor replay.
- Added durable two-person approval for destructive production actions, including a scoped
  SRE/Admin review queue, immutable approval progress events, and database-enforced approval
  count bounds.
- Strengthened production-write verification so declared postcondition evidence must match the
  operation type, environment, target asset, and downstream idempotency key; otherwise execution
  remains incomplete and requires reconciliation.
- Added strict, bounded configuration schemas and rules plus database invariants that permit only
  one published policy per config asset and one current snapshot per asset/environment.
- Added a revision-bound Responses v2 capacity gate that follows every durable Response to a
  terminal projection, measures first persisted events and end-to-end latency, evaluates weighted
  multi-capability workloads independently, and emits immutable privacy-minimized release evidence.

### Changed

- Enterprise Golden Dataset gates no longer synthesize actual results from expected assertions.
  Contract validation reports schema validity only; release evaluation requires complete,
  provenance-bound Responses v2 result envelopes.

- Removed local runtime artifacts, internal QA snapshots, redundant launch wrappers, and an
  unused frontend package.
- Rebuilt the public environment template from the active settings model with safe defaults.
- Upgraded the frontend build and test toolchain to versions without known npm audit findings.
- Hardened release deployment with digest-pinned production images, least-privilege network
  policies, SBOM/provenance attestations and immediately verified keyless image signatures; updated
  Python and frontend dependency locks to remove all currently detected audit findings.

[Unreleased]: https://github.com/SongJok/OpenTrace/compare/main...HEAD
