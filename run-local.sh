#!/usr/bin/env bash
# Run LegalOS on your computer without Docker (macOS; also works on Linux).
#
#   ./run-local.sh          set up (first time) and start everything
#   ./run-local.sh reset    delete all local data (database, uploaded files, settings)
#
# LEGALOS_LOCAL_PREVIEW=1 ./run-local.sh   also allow opening the app through another
#   address (a cloud preview pane or a tunnel). Development only: it relaxes the login
#   cookie and the cross-site request check.
#
# Everything lives in the .local/ folder of the project. Press Ctrl+C to stop.
# Requires: Homebrew packages listed below (the script tells you what is missing).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOCAL="$ROOT/.local"
PG_PORT="${LEGALOS_LOCAL_PG_PORT:-5433}"
API_PORT="${LEGALOS_LOCAL_API_PORT:-8000}"
WEB_PORT="${LEGALOS_LOCAL_WEB_PORT:-3000}"
BREW_PACKAGES="uv node pnpm tesseract tesseract-lang postgresql@17 pgvector"

say() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }
fail() {
  printf '\n\033[31mErro:\033[0m %s\n' "$1" >&2
  shift
  for line in "$@"; do printf '  %s\n' "$line" >&2; done
  exit 1
}
port_busy() { (echo >"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1; }
# Run a setup step quietly; on failure, show its output and stop.
step() {
  if ! "$@" >"$LOCAL/logs/setup.log" 2>&1; then
    tail -30 "$LOCAL/logs/setup.log" >&2
    fail "o passo \"$*\" falhou (registro completo em .local/logs/setup.log)."
  fi
}

has_pgvector() { [ -f "$("$1/pg_config" --sharedir 2>/dev/null)/extension/vector.control" ]; }

find_pg_bin() {
  if [ -n "${PG_BIN:-}" ]; then
    echo "$PG_BIN"
    return
  fi
  if command -v brew >/dev/null 2>&1; then
    # Prefer a Homebrew PostgreSQL that has pgvector installed.
    first=""
    for version in 18 17 16; do
      bin="$(brew --prefix)/opt/postgresql@$version/bin"
      [ -x "$bin/initdb" ] || continue
      [ -n "$first" ] || first="$bin"
      if has_pgvector "$bin"; then
        echo "$bin"
        return
      fi
    done
    if [ -n "$first" ]; then
      echo "$first"
      return
    fi
  fi
  if command -v pg_config >/dev/null 2>&1 && [ -x "$(pg_config --bindir)/initdb" ]; then
    pg_config --bindir
  else
    # Debian/Ubuntu keep server binaries outside PATH.
    ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1
  fi
}

PG_BIN="$(find_pg_bin)"

if [ "${1:-}" = "reset" ]; then
  if [ -n "$PG_BIN" ] && [ -d "$LOCAL/pgdata" ]; then
    "$PG_BIN/pg_ctl" -D "$LOCAL/pgdata" stop -m fast >/dev/null 2>&1 || true
  fi
  rm -rf "$LOCAL"
  echo "Dados locais apagados (.local/). Rode ./run-local.sh para começar do zero."
  exit 0
fi

# --- 1. Check what is installed -------------------------------------------------------

mkdir -p "$LOCAL/logs"
say "Verificando programas necessários"
missing=""
for cmd in uv node pnpm tesseract; do
  command -v "$cmd" >/dev/null 2>&1 || missing="$missing $cmd"
done
[ -n "$PG_BIN" ] && [ -x "$PG_BIN/initdb" ] || missing="$missing postgresql"
if [ -n "$missing" ]; then
  fail "faltam programas:$missing" \
    "No Mac, instale com o Homebrew (https://brew.sh):" \
    "  brew install $BREW_PACKAGES" \
    "Depois rode ./run-local.sh de novo."
fi
if ! has_pgvector "$PG_BIN"; then
  fail "a extensão pgvector não está instalada para o PostgreSQL em $PG_BIN." \
    "No Mac: brew install pgvector" \
    "Se continuar falhando, rode 'brew info pgvector' para ver qual versão do PostgreSQL" \
    "ele suporta e instale essa versão (por exemplo: brew install postgresql@18)."
fi
tesseract --list-langs 2>/dev/null | grep -qx por ||
  fail "o OCR em português não está instalado." "No Mac: brew install tesseract-lang"
node_major="$(node -p 'process.versions.node.split(".")[0]')"
[ "$node_major" -ge 20 ] || fail "Node.js 20 ou mais novo é necessário (você tem $(node -v))." "No Mac: brew upgrade node"
for port in "$API_PORT" "$WEB_PORT"; do
  if port_busy "$port"; then
    fail "a porta $port já está em uso por outro programa." \
      "Feche esse programa ou rode com outra porta, por exemplo:" \
      "  LEGALOS_LOCAL_WEB_PORT=3100 LEGALOS_LOCAL_API_PORT=8100 ./run-local.sh"
  fi
done
echo "Tudo certo (PostgreSQL em $PG_BIN)."

# --- 2. Local settings (created once, then reused) ------------------------------------

if [ ! -f "$LOCAL/env" ]; then
  say "Criando configurações locais em .local/env"
  key="$(cd "$ROOT/backend" && uv run --quiet python -c \
    'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  cat >"$LOCAL/env" <<EOF
# Local development settings, created by run-local.sh. Fictional data only.
export LEGALOS_ENVIRONMENT=development
export LEGALOS_DB_ADMIN_URL="postgresql://postgres@localhost:$PG_PORT/postgres"
export LEGALOS_DATABASE_URL="postgresql+psycopg://legalos_app:local-app@localhost:$PG_PORT/legalos"
export LEGALOS_DATABASE_OWNER_URL="postgresql+psycopg://legalos_owner:local-owner@localhost:$PG_PORT/legalos"
export LEGALOS_DATABASE_APP_ROLE=legalos_app
export LEGALOS_ENCRYPTION_KEY="$key"
export LEGALOS_SESSION_COOKIE_SECURE=false
export LEGALOS_STORAGE_BACKEND=local
export LEGALOS_STORAGE_LOCAL_DIR="$LOCAL/storage"
EOF
fi
# shellcheck disable=SC1091
. "$LOCAL/env"
export LEGALOS_ALLOWED_ORIGINS="[\"http://localhost:$WEB_PORT\"]"
if [ "${LEGALOS_LOCAL_PREVIEW:-}" = "1" ]; then
  export LEGALOS_PREVIEW_MODE=true
fi

# --- 3. Database ----------------------------------------------------------------------

if [ ! -d "$LOCAL/pgdata" ]; then
  say "Criando banco de dados local"
  # Trust authentication is acceptable only because the server listens on localhost.
  "$PG_BIN/initdb" -D "$LOCAL/pgdata" -U postgres --auth=trust -E UTF8 --locale=C >/dev/null
fi
if ! "$PG_BIN/pg_ctl" -D "$LOCAL/pgdata" status >/dev/null 2>&1; then
  say "Iniciando PostgreSQL (porta $PG_PORT)"
  "$PG_BIN/pg_ctl" -D "$LOCAL/pgdata" -l "$LOCAL/logs/postgres.log" -w \
    -o "-p $PG_PORT -c listen_addresses=localhost -c unix_socket_directories=''" start >/dev/null
fi

PIDS=""
cleanup() {
  trap - EXIT INT TERM
  say "Encerrando"
  for pid in $PIDS; do kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; done
  "$PG_BIN/pg_ctl" -D "$LOCAL/pgdata" stop -m fast >/dev/null 2>&1 || true
  echo "Pronto. Seus dados continuam em .local/ (use ./run-local.sh reset para apagar)."
}
trap cleanup EXIT INT TERM

say "Preparando o backend (dependências, banco, dados fictícios)"
cd "$ROOT/backend"
step uv sync
step uv run python -m legalos.dbadmin
step uv run alembic upgrade head
step uv run python -m legalos.storage.bootstrap
step uv run python -m legalos.seed
# Demonstration sample of the legal corpus (not checked against the official text).
step uv run python -m legalos.corpus.ingest --demo
if [ ! -d "$ROOT/test-documents" ]; then
  step uv run python scripts/make_test_corpus.py "$ROOT/test-documents"
fi

say "Preparando o frontend (leva cerca de um minuto)"
cd "$ROOT/frontend"
step pnpm install --frozen-lockfile
# Production build: faster pages and the same behaviour as the real deployment. The API
# address is fixed at build time, so the build runs on every start.
step env API_INTERNAL_URL="http://localhost:$API_PORT" pnpm build

# --- 4. Start the API, the worker and the web app -------------------------------------

say "Iniciando o sistema"
set -m  # each background process gets its own group, so Ctrl+C stops all of them
cd "$ROOT/backend"
uv run --quiet uvicorn legalos.main:app --port "$API_PORT" >"$LOCAL/logs/api.log" 2>&1 &
PIDS="$PIDS $!"
uv run --quiet python -m legalos.worker >"$LOCAL/logs/worker.log" 2>&1 &
PIDS="$PIDS $!"
cd "$ROOT/frontend"
PORT="$WEB_PORT" pnpm start >"$LOCAL/logs/web.log" 2>&1 &
PIDS="$PIDS $!"
set +m

for _ in $(seq 1 90); do
  curl -sf "http://localhost:$WEB_PORT/api/health" >/dev/null 2>&1 && break
  sleep 2
done
curl -sf "http://localhost:$WEB_PORT/api/health" >/dev/null 2>&1 ||
  fail "o sistema não respondeu. Veja os registros em .local/logs/ (api.log, worker.log, web.log)."

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  ai_mode="IA real (Claude, da Anthropic)"
else
  ai_mode="IA simulada (demonstração). Para usar a IA real, rode:
               echo 'export ANTHROPIC_API_KEY=\"sua-chave\"' >> .local/env
               e reinicie com ./run-local.sh"
fi

cat <<EOF

────────────────────────────────────────────────────────────
  LegalOS está rodando em  http://localhost:$WEB_PORT
  Modo de IA:  $ai_mode

  Entre com:   bruno.costa@silva.example
  Senha:       senha-de-teste-123
  (outros usuários fictícios: veja o README; todos usam a mesma senha)

  No primeiro acesso, configure a verificação em duas etapas
  com um app autenticador no celular.

  Documentos fictícios para enviar: pasta test-documents/

  Para parar: Ctrl+C
────────────────────────────────────────────────────────────
EOF
if command -v open >/dev/null 2>&1; then open "http://localhost:$WEB_PORT" || true; fi

wait
