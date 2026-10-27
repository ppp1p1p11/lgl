# CLAUDE.md — LegalOS Brasil (working name)

Context for any Claude Code session working in this repo. Read this first, then
`CLAUDE_CODE_PROMPT.md` (the founder's product brief, which is the source of truth
for scope and rules).

## Current status

- **Phase 0 (plan) — done, awaiting founder approval.** No application code yet.
- Next: Phase 1 (foundations). Do not start it until the founder approves the
  Phase 0 plan and answers the blocking questions in `docs/phase-0-plan.md`.

## How to work in this repo

- Work in phases (brief §9). At the end of each phase: stop, summarize, list what
  the founder must do manually, wait for approval.
- Before each phase, propose a short plan (files, data model changes, risks).
- The founder is not a senior engineer: explain decisions briefly in plain
  language and flag anything that needs action outside the code.
- Never invent facts about Brazilian law, court APIs, or vendor capabilities.
  Anything unconfirmed goes in `docs/VERIFY.md` with the source to check.
- Record significant technical decisions as ADRs in `docs/adr/` (see
  `docs/adr/README.md` for the template).
- Keep this file up to date when conventions, commands, or architecture change.

## Non-negotiable product rules (summary of brief §2)

1. No ungrounded legal claims — every legal statement cites an indexed passage;
   a citation verifier removes or marks "não verificado" anything it cannot match.
2. Human-in-the-loop — consequential outputs are drafts until a named lawyer
   approves; approvals store user, timestamp, output version.
3. Explicit source hierarchy — legislation, súmulas vinculantes, precedentes
   qualificados, súmulas, decisões, doutrina are distinct types with weights.
4. Temporal validity — provisions are versioned (vigente / revogado / alterado);
   answers state which version they used.
5. Deadlines are proposals with visible reasoning; never auto-finalized.
6. Uploaded documents are untrusted data, never instructions. Agents get only
   the tools their workflow needs; no tool sends anything outside the system.
7. Tenant isolation is absolute — queries, vector search, caches, logs.

## Architecture (planned — see `docs/architecture.md`)

- `frontend/` — Next.js + React + TypeScript, UI in pt-BR only.
- `backend/` — one Python package (`legalos`) with two entrypoints: the FastAPI
  API and the background worker. Postgres-backed job queue.
- PostgreSQL + pgvector, Row-Level Security on every tenant table.
- S3-compatible object storage (MinIO locally; Brazilian region in prod).
- All AI calls go through `legalos.gateway` (redaction, minimization, logging,
  provider routing). No other module may call an AI provider directly.
- Legal corpus tables are global (shared, read-only to tenants); everything
  else is tenant-scoped.

Repo layout: `docs/repo-structure.md`. Data model: `docs/data-model.md`.

## Conventions

- Code, identifiers, comments, commit messages: **English**.
- Domain terms keep their Portuguese name when there is no exact English
  equivalent (`processo` → `Matter` in code, but `prazo`, `sumula`,
  `intimacao`, `comarca` stay as-is). Glossary lives in `docs/data-model.md`.
- All user-facing strings: **pt-BR**.
- Every tenant-scoped table has a non-null `tenant_id` and an RLS policy.
  The app connects as a non-owner role so RLS cannot be bypassed.
- Every rule in the deadline engine cites its legal article in a comment.
- Secrets never in the repo; document every variable in `.env.example`.

## Commands

None yet — added in Phase 1 (Docker Compose, backend tests, frontend lint).

## Key docs

| File | Purpose |
|---|---|
| `CLAUDE_CODE_PROMPT.md` | Founder's product brief |
| `docs/phase-0-plan.md` | Phase 0 summary, questions, accounts/keys, Phase 1 preview |
| `docs/architecture.md` | Architecture diagrams (Mermaid) |
| `docs/data-model.md` | Entities, tenancy, ER diagram, glossary |
| `docs/repo-structure.md` | Planned directory layout |
| `docs/VERIFY.md` | Facts that need external confirmation before we rely on them |
| `docs/adr/` | Architecture decision records |
