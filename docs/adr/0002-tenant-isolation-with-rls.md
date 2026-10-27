# ADR-0002: Tenant isolation with Postgres Row-Level Security

- Status: Proposed
- Date: 2026-10-27

## Context
Brief rule 7: no query, embedding search, cache or log may cross firms. A
single bug in application code (a missing `WHERE tenant_id = …`) must not be
enough to leak another firm's case files.

## Decision
- Shared database, shared schema; every firm-scoped table has a non-null
  `tenant_id`.
- Row-Level Security is enabled **and forced** on every firm-scoped table,
  with a policy comparing `tenant_id` to `current_setting('app.tenant_id')`.
- The backend sets `app.tenant_id` with `SET LOCAL` at the start of every
  transaction, from the authenticated session — never from request input.
- The application connects as a database role that does not own the tables
  and does not have `BYPASSRLS`. Migrations run as a separate owner role.
- Vector search (`document_chunks.embedding`) runs on the same RLS-protected
  table. No separate vector store.
- Background jobs carry `tenant_id` and set it the same way before touching
  data.
- The legal corpus is global and read-only for the application role.
- Object storage keys start with the tenant id; signed URLs are only issued
  for keys of the caller's tenant.
- CI includes tests proving tenant A cannot read, update, or vector-search
  tenant B's data, including when the application "forgets" the filter.

## Consequences
- Defence in depth: the database enforces isolation even if app code is
  wrong.
- Approximate vector search combined with a tenant filter can return fewer
  results than requested; we must check pgvector's filtered-search behaviour
  (`docs/VERIFY.md` INF-2) and test recall per tenant. If needed, partition
  `document_chunks` by tenant.
- Every new table needs a migration that adds the policy; we will add a test
  that fails if any table with a `tenant_id` column lacks RLS.

## Alternatives considered
- **Database per tenant:** strongest isolation, but heavy to operate for
  dozens of small firms and complicates the shared legal corpus.
- **Schema per tenant:** similar operational cost; migrations multiply.
- **Application-level filtering only:** one missed filter leaks data. Rejected.
