# ADR-0004: Postgres-backed job queue for the MVP

- Status: Accepted (2026-10-27)
- Date: 2026-10-27

## Context
OCR, embedding, AI summaries, corpus ingestion and DataJud syncs are slow and
must run in the background with retries. The brief prefers a simple
Postgres-backed queue and moving to Temporal only if needed.

## Decision
- Jobs are rows in a `jobs` table in Postgres. Workers claim jobs with
  `SELECT … FOR UPDATE SKIP LOCKED`, run them, and record the result, the
  attempt count and the error.
- Each job stores its `tenant_id` (null only for global corpus jobs) and the
  worker sets the tenant context before running it.
- Retries with backoff; a job that keeps failing is marked dead and visible
  in the admin panel (Phase 6).
- Implemented in-house (a small module with tests, `legalos.jobs`): the logic is
  short, and a library (e.g. `procrastinate`) would add concepts we do not need yet.

## Consequences
- No extra infrastructure (no Redis, no message broker).
- Enqueuing a job in the same transaction as the data change means we never
  lose a job or run one for data that was rolled back.
- Throughput is limited compared with a dedicated broker; fine for MVP
  volumes. Long multi-step workflows may later justify Temporal.

## Alternatives considered
- **Celery + Redis:** popular, but adds Redis and its own failure modes.
- **Temporal:** excellent for long workflows, heavy for the MVP.
- **Cloud queue service:** ties local dev to the cloud.
