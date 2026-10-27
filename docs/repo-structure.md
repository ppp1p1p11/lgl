# Repo structure (Phase 0 proposal)

One repository ("monorepo") with the web app, the backend, evaluations and
docs. Folders marked *(Phase N)* are created when that phase starts — we do
not create empty scaffolding ahead of time.

```
.
├── CLAUDE.md                     # conventions for every Claude Code session
├── CLAUDE_CODE_PROMPT.md         # founder's product brief
├── README.md                     # how to run locally (Phase 1)
├── .env.example                  # every env var, no real values (Phase 1)
├── docker-compose.yml            # postgres+pgvector, seaweedfs (local S3), api, worker, web
├── .github/workflows/ci.yml      # lint, typecheck, tests, dependency scan (Phase 1)
│
├── backend/                      # Python 3.12, FastAPI, managed with uv (Phase 1)
│   ├── pyproject.toml
│   ├── alembic/                  # migrations, incl. RLS policies and roles
│   ├── src/legalos/
│   │   ├── main.py               # FastAPI app entrypoint
│   │   ├── worker.py             # background worker entrypoint
│   │   ├── config.py             # settings from LEGALOS_* environment variables
│   │   ├── dbadmin.py            # one-time DB bootstrap: owner role, app role, database
│   │   ├── seed.py               # fictional firms and users (dev only)
│   │   ├── core/                 # db session + tenant context, crypto, logging, middleware
│   │   ├── audit/                # append-only audit log
│   │   ├── auth/                 # login, MFA, sessions, roles
│   │   ├── tenancy/              # firms, memberships, seed data
│   │   ├── storage/              # object storage, signed URLs
│   │   ├── jobs/                 # Postgres job queue
│   │   ├── matters/              # clients, processos, parties, timeline   (Phase 2)
│   │   ├── documents/            # upload, OCR, classify, extract, chunk    (Phase 2)
│   │   ├── gateway/              # AI gateway: providers, redaction, call log (Phase 2)
│   │   ├── agents/               # orchestrators, scoped tools, traces     (Phase 2+)
│   │   ├── citations/            # citation verifier                       (Phase 2+)
│   │   ├── corpus/               # ingestion per source, chunking, search  (Phase 3)
│   │   ├── drafting/             # templates, generation, .docx export     (Phase 4)
│   │   ├── deadlines/            # rule sets (cpc, clt, juizados), calendars (Phase 5)
│   │   └── datajud/              # read-only DataJud connector             (Phase 5)
│   └── tests/
│       ├── test_tenant_isolation.py   # tenant A cannot read tenant B, incl. vectors
│       └── ...
│
├── frontend/                     # Next.js + TypeScript, pnpm, pt-BR only (Phase 1)
│   ├── app/                      # App Router pages
│   ├── components/
│   ├── lib/api/                  # typed client generated from the backend OpenAPI schema
│   └── messages/pt-BR.json       # all UI strings in one place
│
├── evals/                        # (Phase 3)
│   ├── questions/                # ≥50 questions + expected cited provisions (YAML)
│   ├── run.py                    # citation accuracy, recall, hallucinated-citation rate
│   └── reports/
│
├── infra/
│   ├── local/                    # local-only config (SeaweedFS S3 credentials for dev)
│   └── ...                       # IaC for the Brazilian region (Phase 6)
│
└── docs/
    ├── architecture.md
    ├── data-model.md
    ├── repo-structure.md
    ├── phase-0-plan.md
    ├── VERIFY.md
    ├── adr/                      # architecture decision records
    ├── compliance/               # LGPD, OAB checklists for lawyer review (Phase 2+)
    └── security/threat-model.md  # (Phase 1)
```

## Why this shape

- **One Python package, two entrypoints (API + worker):** the worker needs the
  same models, tenant context and gateway as the API. Splitting them into
  separate services now would only add deployment work.
- **Typed API client generated from OpenAPI:** the frontend and backend cannot
  silently drift apart.
- **Tests live next to the backend** and the tenant-isolation test is a
  first-class file, because it is a non-negotiable rule.

## Tooling (proposed, confirmed in Phase 1)

| Area | Tool |
|---|---|
| Python deps / venv | uv |
| Python lint + format | ruff |
| Python types | mypy (strict on `core`, `auth`, `tenancy`, `gateway`, `deadlines`) |
| Python tests | pytest, against a real Postgres in Docker (no SQLite: RLS and pgvector must be tested for real) |
| Migrations | Alembic |
| JS package manager | pnpm |
| JS lint / format | ESLint + Prettier |
| JS tests | Vitest; Playwright for a few end-to-end flows later |
| Dependency scanning | GitHub Dependabot + `pip-audit` / `pnpm audit` in CI |
