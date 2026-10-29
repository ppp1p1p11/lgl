# LegalOS Brasil (working name)

A Portuguese-language workspace for small and midsize Brazilian law firms. AI agents read
the firm's documents, research Brazilian law with verifiable citations, draft work, and
propose deadlines. A lawyer approves every consequential output.

- Product brief: [`CLAUDE_CODE_PROMPT.md`](CLAUDE_CODE_PROMPT.md)
- Plan, architecture and decisions: [`docs/`](docs/) (start with
  [`docs/phase-0-plan.md`](docs/phase-0-plan.md))
- Conventions for AI-assisted development: [`CLAUDE.md`](CLAUDE.md)

**Status:** Phase 2a is done. You can log in with MFA, register clients and processos,
upload documents (PDF, Word, photos), read their text (including scanned pages, via OCR)
next to the original, and search inside a processo. Firm isolation is enforced by the
database and covered by tests. AI features arrive in Phase 2b.

## Run it on your computer

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and
running.

```bash
cp .env.example .env          # local settings (fictional, development-only values)
docker compose up --build     # first run takes a few minutes
```

In a second terminal, add the fictional firms and users:

```bash
docker compose run --rm api python -m legalos.seed
```

Then open **http://localhost:3000** and log in, for example as
`bruno.costa@silva.example` with password `senha-de-teste-123`. Bruno belongs to two
firms, so you can try the firm switcher.

The first login asks you to set up MFA. Scan the QR code with any authenticator app
(Google Authenticator, Microsoft Authenticator, 1Password…), type the 6-digit code, and
save the recovery codes it shows.

To try uploads, generate fictional test documents (digital PDFs, scans of different
quality, photos and Word files). This needs [uv](https://docs.astral.sh/uv/) installed;
run it from the `backend` folder:

```bash
uv run python scripts/make_test_corpus.py ../test-documents
```

Files named `*-ilegivel.pdf` are deliberately unreadable scans: the app should warn
"texto pode conter erros" for them.

Useful addresses:

| What | Where |
|---|---|
| Web app | http://localhost:3000 |
| API documentation | http://localhost:8000/api/docs |
| Database | `localhost:5432` (user `postgres`, password from `.env`) |

To stop: `Ctrl+C`, then `docker compose down`. To also erase all local data:
`docker compose down -v`.

## Development without Docker (for developers)

Backend (Python 3.12+, [uv](https://docs.astral.sh/uv/), and Tesseract OCR with the
Portuguese model: `apt install tesseract-ocr tesseract-ocr-por` or
`brew install tesseract tesseract-lang`), from `backend/`:

```bash
uv sync
uv run pytest            # needs Postgres with pgvector; see LEGALOS_TEST_ADMIN_URL in tests/conftest.py
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Frontend (Node 22, pnpm), from `frontend/`:

```bash
pnpm install
pnpm dev                 # http://localhost:3000, forwards /api to http://localhost:8000
pnpm lint && pnpm typecheck && pnpm test
```

After changing backend API endpoints, regenerate the frontend's typed client:

```bash
cd backend && uv run python scripts/export_openapi.py && cd ../frontend && pnpm gen:api
```

CI (GitHub Actions) runs all of the above, plus dependency audits and a Docker build, on
every pull request.
