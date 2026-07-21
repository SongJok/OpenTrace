## What changed

Describe the user-visible outcome and the affected runtime path.

## Why

Explain the problem, trade-offs, and any compatibility considerations.

## Verification

- [ ] Relevant backend tests pass
- [ ] Frontend tests/build pass when applicable
- [ ] Import boundaries pass
- [ ] Configuration/docs are updated
- [ ] No secrets, local state, or generated artifacts are included

## Governance checklist

- [ ] Tenant/workspace/user/Project boundaries are preserved
- [ ] Write or destructive operations use durable approval/idempotency
- [ ] API work does not execute models or tools in the request process
