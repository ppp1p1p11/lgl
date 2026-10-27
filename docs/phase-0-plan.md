# Phase 0 — Plan

Status: **complete, waiting for your approval.** No application code was written.

## What Phase 0 produced

| Deliverable (brief §9) | Where |
|---|---|
| (a) Questions for you | §1 below |
| (b) Architecture diagram (Mermaid) | `docs/architecture.md` |
| (c) Data model | `docs/data-model.md` |
| (d) Repo structure | `docs/repo-structure.md` |
| (e) Things that need external confirmation | `docs/VERIFY.md` |
| (f) Accounts and keys you must create | §2 below |
| `CLAUDE.md` | repo root |
| First ADRs (all "Proposed") | `docs/adr/` |

The architecture in one sentence: a pt-BR Next.js web app talks to a Python
(FastAPI) backend. A background worker does the slow work. PostgreSQL holds
everything, including search vectors and the job queue, with each firm's
rows locked by the database itself (Row-Level Security). All AI calls go
through one gateway that removes personal data and logs every call. All
stored data stays in a Brazilian cloud region.

---

## 1. Questions for you

**Blocking** questions affect Phase 1. The others can wait, but earlier answers help.

### Blocking for Phase 1

- **Q1. Cloud provider.** Where will production run? I recommend **AWS São
  Paulo (`sa-east-1`)**. It's the most likely place for in-region managed
  Postgres with pgvector, S3, and possibly Claude models via Bedrock, but
  each of these is still in `VERIFY.md` (AI-1, INF-1). Other options are GCP,
  Azure, or a Brazilian provider. Phase 1 runs entirely on your laptop or in
  CI, so this only has to be settled by the end of Phase 1.
- **Q2. Do you approve the stack in ADR-0001 and the RLS approach in
  ADR-0002?**
- **Q3. MFA method at launch.** I recommend an authenticator app (TOTP) for
  everyone, mandatory. SMS is weaker and costs money per message. Passkeys
  could come later. Do you agree?
- **Q4. Roles.** Are these right?
  - **Sócio:** everything, including firm settings and billing later.
  - **Advogado:** can approve AI outputs and confirm prazos.
  - **Estagiário:** can draft, can't approve.
  - **Administrativo:** clients, documents and tasks, no AI legal outputs.
  - Open point: should an advogado be able to approve work only on processos
    assigned to them, or on any processo in the firm?
- **Q5. Fake seed data.** Can I invent two or three fictional firms with
  fictional clients and processos for tests? I'll use valid-format but fake
  CPF/CNPJ and CNJ numbers. No real data is needed.
- **Q6. Authentication (ADR-0003).** Build login + MFA inside our backend
  (keeps data in Brazil, more code we own), or use a hosted identity service
  (less code, residency to verify)? I recommend in-house, built on standard
  libraries, with a security review before the pilot.

### Needed before Phase 2–3

- **Q7. Practice areas for the pilot.** The brief names labor law as core.
  Which 1–3 areas do your pilot firms work in most (trabalhista, cível,
  consumidor, família, previdenciário, tributário)? This decides the corpus
  coverage and templates to build first.
- **Q8. Pilot firms.** Do you have 2–3 firms willing to pilot? Could they
  share 10–20 **anonymized** real PDFs (especially scanned ones) so we can
  test OCR and summaries on real material?
- **Q9. A Brazilian lawyer** to review the compliance checklists, the
  deadline rules, and the 50-question eval set. Who will it be, and roughly
  how many hours can they give?
- **Q10. AI provider preference and budget.** Any preference, such as
  Anthropic directly or via a cloud's Brazilian region? What monthly AI
  spend is acceptable during the pilot? The gateway will enforce per-firm
  limits.
- **Q11. Which courts first?** Deadline calendars are per court and comarca.
  Which states and tribunals do your pilot firms file in most (e.g. TJSP,
  TRT-2, TRF-3)?

### Can wait

- **Q12. Product name and domain.** "LegalOS Brasil" is a working name. A
  `.com.br` domain needs a CPF/CNPJ to register.
- **Q13. Company.** Is there a CNPJ yet? Contracts with cloud and AI
  providers, the DPA with firms, and the terms of service will need one.
- **Q14. Word export.** Should exported .docx files follow each firm's own
  letterhead template (upload a .docx model), or a clean standard layout at
  first?

---

## 2. Accounts and keys you must create

**Phase 1 needs nothing new beyond this GitHub repo.** Everything runs
locally in Docker with fake data. The list below is in order of when you'll
need each item. Turn on MFA for every account, and never paste keys into
chat or commit them; we'll use `.env` files and the cloud's secret manager.

| When | Account / item | Why | Notes |
|---|---|---|---|
| Now | GitHub (exists) — make sure **Actions** is enabled for the repo | CI for tests and lint | Free tier is enough to start |
| End of Phase 1 | **Cloud account** (recommended: AWS) with billing alerts set (e.g. at R$ 200 / R$ 500) | Hosting in São Paulo | Use an organization/root account with MFA, then a separate admin user. Don't use the root account day to day |
| Phase 2 | **AI provider access**: Anthropic API key and/or model access enabled in the cloud's AI service (e.g. Bedrock) in São Paulo, if available (VERIFY AI-1) | Summaries, extraction, research | Ask for zero data retention / no-training terms in writing (VERIFY AI-2) |
| Phase 1–2 | **Error tracking** account (e.g. Sentry) — or decide to self-host | Bugs and crashes | Check where it stores data (VERIFY INF-4) |
| Phase 1 end | **Transactional email** (e.g. AWS SES) and a domain | Invites, password reset, MFA recovery | Needs a verified domain |
| Phase 5 | **CNJ DataJud** API access | Public process metadata | Check the current key and terms (VERIFY SRC-6) |
| Before pilot | **Company (CNPJ)**, `.com.br` domain at Registro.br | Contracts, DPA, invoices later | |
| Before pilot | **Brazilian lawyer** engagement for compliance review | LGPD, OAB, terms of service, DPA | See `VERIFY.md` §5 |
| Before pilot | **Encarregado (DPO)** contact | LGPD | Check whether the small-agent rules exempt us (VERIFY REG-4) |

---

## 3. Main risks I see

1. **AI model availability in Brazil (AI-1).** If the model can't run in São
   Paulo, every AI call is an international data transfer. That needs
   redaction, standard contractual clauses, and clear disclosure to firms.
   This is solvable, but it must be designed in from Phase 2, not added
   later.
2. **Access to legal sources (SRC-1…7).** If Planalto or a court has no
   reusable feed, ingestion may need a slower or different route. We will
   not scrape in breach of their terms.
3. **Deadline liability.** A wrong prazo can cost a case. Mitigations:
   - prazos are always proposals, with reasoning shown
   - every rule has tests
   - a lawyer reviews the rule set
   - the terms of service state that the lawyer confirms the date
4. **OCR quality** on scanned court PDFs drives everything downstream. We'll
   test it on real anonymized samples (Q8) before relying on it.
5. **Scope creep.** The MVP wedge is already ambitious for one founder. I'll
   keep each phase small and push "nice to have" items to a backlog.

---

## 4. Preview: Phase 1 plan (for approval, not started)

**Goal:** a running skeleton with secure multi-firm foundations, and no AI yet.

| Item | Detail |
|---|---|
| Monorepo scaffolding | `backend/` (FastAPI, uv, ruff, mypy, pytest), `frontend/` (Next.js, pnpm, ESLint), `README.md`, `.env.example` |
| Docker Compose | Postgres + pgvector, MinIO (local S3), api, worker, web |
| Database | Alembic migrations; owner role vs app role (no `BYPASSRLS`); tables `tenants`, `users`, `memberships`, `mfa_factors`, `sessions`, `audit_log`, `jobs`, plus a minimal `document_chunks` table with a vector column so isolation can be tested |
| Auth | Email + password (Argon2id), mandatory TOTP MFA, recovery codes, server-side sessions, roles, login rate limiting |
| Tenancy | Tenant context per request and per job (`SET LOCAL`), RLS policies, signed URLs scoped to the tenant |
| Audit log | Append-only; login, MFA and permission events from day one |
| Frontend | pt-BR login, MFA setup, firm switcher, an empty "Processos" page |
| Seed data | 2–3 fictional firms with users in every role |
| Tests | **Tenant A cannot read, write, or vector-search tenant B**, including with the app filter removed; every table with `tenant_id` has RLS enabled; auth and role tests |
| CI | GitHub Actions: lint, typecheck, tests against real Postgres, dependency scan |
| Docs | `docs/security/threat-model.md` (first version), `CLAUDE.md` commands section |

**Risks for Phase 1:**
- Getting RLS right with the connection pool (`SET LOCAL` must be inside each
  transaction).
- Making sure pgvector filtered search behaves well under RLS (INF-2).

**What you'll need to do in Phase 1:** answer Q1–Q6, make sure GitHub
Actions is enabled, and install Docker Desktop if you want to run it locally.
I'll write step-by-step run instructions.
