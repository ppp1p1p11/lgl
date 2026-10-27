# ADR-0001: Stack and monorepo layout

- Status: Accepted (2026-10-27)
- Date: 2026-10-27

## Context
The brief suggests Next.js + TypeScript, Python + FastAPI, PostgreSQL +
pgvector, and Docker Compose. The founder is not a senior engineer, so the
stack should be common, well documented, and easy to hire for in Brazil. The
AI and document-processing ecosystem (OCR, PDF, embeddings, evals) is
strongest in Python.

## Decision
Accept the suggested stack, with these specifics:
- One repository with `frontend/` (Next.js, pnpm) and `backend/` (Python 3.12,
  uv). See `docs/repo-structure.md`.
- One backend Python package with two entrypoints: the API and the worker.
- PostgreSQL is the only stateful service besides object storage: it holds
  relational data, full-text search, vectors (pgvector), and the job queue.
- The frontend calls the backend through a client generated from the
  backend's OpenAPI schema.
- Local development: Docker Compose with Postgres+pgvector and an S3-compatible store.
  *Amended in Phase 1:* the local store is SeaweedFS (Apache-2.0), because MinIO's
  community Docker images are no longer published. Production uses the cloud provider's
  S3 service; only the endpoint and credentials differ.

## Consequences
- Two languages (TypeScript and Python) to maintain; accepted because each is
  the default in its area.
- Using Postgres for everything keeps operations simple. If search or queue
  load outgrows it, we can move one piece out later without changing the
  others.

## Alternatives considered
- **Full-stack TypeScript (Next.js API routes):** one language, but weaker
  libraries for OCR, PDF, evals and ML.
- **Separate vector database (e.g. a hosted vector DB):** another service to
  secure and keep in Brazil, and tenant isolation would have to be rebuilt
  outside RLS. Not needed at MVP scale.
- **Django instead of FastAPI:** batteries included (admin, auth), but the
  brief proposes FastAPI and our API is mostly JSON for a separate frontend.
  Reasonable either way; not worth deviating.
