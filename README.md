# LegalOS Brasil (working name)

A Portuguese-language workspace for small and midsize Brazilian law firms. AI agents read
the firm's documents, research Brazilian law with verifiable citations, draft work, and
propose deadlines. A lawyer approves every consequential output.

- Product brief: [`CLAUDE_CODE_PROMPT.md`](CLAUDE_CODE_PROMPT.md)
- Plan, architecture and decisions: [`docs/`](docs/) (start with
  [`docs/phase-0-plan.md`](docs/phase-0-plan.md))
- Conventions for AI-assisted development: [`CLAUDE.md`](CLAUDE.md)

**Status:** everything that does not need an outside service is built and can be tried
in the browser with fictional data:

- Login with MFA, firms, roles; a sócio adds and removes people (Administração → Equipe).
- Clients, processos, parties, timeline (movements typed by hand for now).
- Documents: upload PDF/Word/photos, OCR, side-by-side reading, search.
- **Análise por IA** of a document: type, facts with the source passage, cited summary.
- **Prazos**: a calculator that shows its reasoning step by step (CPC, CLT, Juizados),
  a holiday calendar, and confirmation by a lawyer, which creates a task.
- **Pesquisa jurídica**: answers only from the indexed legal texts, each sentence linked
  to the provision it comes from.
- **Minutas**: drafts built from a template, the processo's documents and the legal
  texts; edit per section, approve, download as Word.
- Review and approval of every AI output by a named lawyer; audit log; AI cost report.

**What is still missing** (needs outside services or a lawyer): the real AI key, the
official legal texts (the bundled sample of CPC articles is an *unverified demonstration*),
court data (DataJud), e-mail, and deployment in Brazil. See
[`docs/before-pilot.md`](docs/before-pilot.md).

**AI modes:** without an Anthropic API key, the app uses a *simulated* AI (simple rules,
clearly labelled "IA simulada") so you can try the whole flow. With `ANTHROPIC_API_KEY`
set, it uses Claude. Use only fictional or public documents for now: real client data
needs a lawyer's review of the data-transfer rules first.

## Run it on a Mac without Docker (simplest)

1. Install [Homebrew](https://brew.sh) if you don't have it (one command, shown on that
   page). Then open the **Terminal** app and install the programs LegalOS needs:

   ```bash
   brew install uv node pnpm tesseract tesseract-lang postgresql@17 pgvector
   ```

2. Get the code. If you don't have it yet:

   ```bash
   git clone https://github.com/ppp1p1p11/lgl.git
   cd lgl
   ```

   If the repository is private, Terminal will ask you to sign in to GitHub; using the
   [GitHub Desktop](https://desktop.github.com) app to clone it is the easiest option.
   Until the pull request is merged, also run `git checkout claude/youthful-allen-5sm5rq`.

3. Start everything:

   ```bash
   ./run-local.sh
   ```

   The first run takes a few minutes. It creates a private database and a settings file
   inside the project's `.local/` folder, adds the fictional firms, and creates fictional
   documents in `test-documents/`. Then it opens **http://localhost:3000** in your
   browser and shows the login details. Press **Ctrl+C** in the Terminal to stop.

   To erase all local data and start over: `./run-local.sh reset`.

   To use the real AI instead of the simulated one, add your key once (it stays only on
   your computer, in `.local/env`) and restart:

   ```bash
   echo 'export ANTHROPIC_API_KEY="sua-chave"' >> .local/env
   ./run-local.sh
   ```

   To open the app through another address (for example a tunnel or a cloud preview),
   start it with `LEGALOS_LOCAL_PREVIEW=1 ./run-local.sh`. Development only.

   If something is missing, the script says exactly what to install. If it stops with
   an error, the details are in `.local/logs/`.

## Run it with Docker

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and
running.

```bash
cp .env.example .env          # local settings (fictional, development-only values)
docker compose up --build     # first run takes a few minutes
```

In a second terminal, add the fictional firms and users, and the demonstration sample
of legal texts:

```bash
docker compose run --rm api python -m legalos.seed
docker compose run --rm api python -m legalos.corpus.ingest --demo
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
