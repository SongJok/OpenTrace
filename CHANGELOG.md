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

### Changed

- Removed local runtime artifacts, internal QA snapshots, redundant launch wrappers, and an
  unused frontend package.
- Rebuilt the public environment template from the active settings model with safe defaults.
- Upgraded the frontend build and test toolchain to versions without known npm audit findings.

[Unreleased]: https://github.com/SongJok/OpenTrace/compare/main...HEAD
