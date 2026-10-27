# Architecture Decision Records

Short notes on significant technical decisions: what we chose, why, and what
we gave up. One file per decision, numbered, never renumbered. If a decision
changes, write a new ADR that supersedes the old one and update the old one's
status.

Status values: `Proposed` (waiting for founder approval) · `Accepted` ·
`Superseded by ADR-NNNN` · `Rejected`.

## Template

```markdown
# ADR-NNNN: Title

- Status: Proposed
- Date: YYYY-MM-DD

## Context
What problem are we solving? What constraints apply?

## Decision
What we will do.

## Consequences
What gets easier, what gets harder, what we must watch.

## Alternatives considered
Briefly, and why not.
```

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-stack-and-monorepo.md) | Stack and monorepo layout | Proposed |
| [0002](0002-tenant-isolation-with-rls.md) | Tenant isolation with Postgres Row-Level Security | Proposed |
| [0003](0003-authentication-in-house.md) | Authentication and MFA built into the backend | Proposed |
| [0004](0004-postgres-job-queue.md) | Postgres-backed job queue for the MVP | Proposed |
