# Security Policy

## Supported versions

OpenTrace is currently in the `0.x` development series. Security fixes are applied to the
latest commit on `main`; older snapshots are not maintained as separate release lines.

## Reporting a vulnerability

Please do not disclose a suspected vulnerability in a public issue.

Use GitHub's **Security → Report a vulnerability** workflow for this repository. Include:

- affected commit or version;
- a minimal reproduction;
- expected impact and attack prerequisites;
- any suggested mitigation, if available.

Maintainers should acknowledge a complete report within 7 days and provide a remediation
status within 14 days. Timelines may vary with severity and reproduction complexity.

## Deployment guidance

- Never commit `.env`, database dumps, credentials, private keys, or production logs.
- Replace all development passwords and configure `APP_SECRET_KEY`, `JWT_SECRET`, and
  `DATA_SECRET_KEY` before staging or production deployment.
- Enable tenant RLS only together with `TRUSTED_TENANT_HEADER_SECRET` and a trusted proxy.
- Use read-only database accounts for DataAgent data sources.
- Keep dynamic Skill execution disabled unless an isolated runner is configured.
- Restrict CORS, connector callback origins, outbound web domains, and exposed ports.

See `.env.example`, `docs/ENV_PROFILES.md`, and `docs/runbooks/tenant-rls-staging.md` for
the relevant controls.

## Time-bounded dependency exceptions

Security audit exceptions must be machine-readable in `security/npm-audit-allowlist.json`, name one
advisory and package, include an owner/reason, and expire within 30 days. `npm run audit:security`
continues to fail on every non-allowlisted high/critical advisory and on expired exceptions. The current
React Router exception is limited to GHSA-qwww-vcr4-c8h2 because OpenTrace does not use unstable RSC APIs;
it expires on 2026-08-15 and must be removed as soon as an upstream patched stable release is available.
