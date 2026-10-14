#!/usr/bin/env bash
# Sobe backend (FastAPI) e frontend (Next.js) com um único comando.
#
#   ./scripts/dev.sh              prepara o que faltar e sobe os dois servidores
#   ./scripts/dev.sh --setup-only só prepara (venv, dependências, .env)
#   ./scripts/dev.sh --preflight  só verifica portas e servidores já rodando
#
# Variáveis opcionais: BACKEND_PORT (8000), FRONTEND_PORT (3000), API_LOG
# (ficheiro para o log bruto da API) e qualquer variável do backend
# (ex.: DATABASE_URL), que tem precedência sobre o .env.
# Ctrl+C encerra os dois; se um deles cair, o outro também é encerrado.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
VENV="$ROOT/.venv"
PYTHON="$VENV/bin/python"
API_URL="http://127.0.0.1:$BACKEND_PORT"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

require() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 não encontrado. $2"
}

setup_backend() {
  require python3 "Instale Python 3.13."
  if [ ! -x "$PYTHON" ]; then
    bold "▸ Criando ambiente virtual em .venv"
    python3 -m venv "$VENV"
  fi
  # Reinstala só quando o requirements.txt muda.
  local stamp="$VENV/.requirements.sha256"
  local current
  current="$(shasum -a 256 "$ROOT/backend/requirements.txt" | cut -d' ' -f1)"
  if [ ! -f "$stamp" ] || [ "$(cat "$stamp")" != "$current" ]; then
    bold "▸ Instalando dependências do backend"
    "$PYTHON" -m pip install -q --disable-pip-version-check -r "$ROOT/backend/requirements.txt"
    echo "$current" > "$stamp"
  fi
  if [ ! -f "$ROOT/backend/.env" ]; then
    bold "▸ Criando backend/.env local com segredos aleatórios"
    "$PYTHON" - "$ROOT/backend" <<'PY'
import pathlib, re, secrets, sys
backend = pathlib.Path(sys.argv[1])
values = {
    "JWT_SECRET_KEY": secrets.token_hex(32),
    "BOOTSTRAP_TEACHER_PASSWORD": secrets.token_urlsafe(18),
    "BOOTSTRAP_STUDENT_PASSWORD": secrets.token_urlsafe(18),
    # Login por perfil (professor/aluno_1/aluno_2) usado pelo painel local.
    "ENABLE_SWAGGER_DEMO_ACCOUNTS": "true",
}
text = (backend / ".env.example").read_text()
for name, value in values.items():
    text = re.sub(rf"^{name}=.*$", f"{name}={value}", text, flags=re.M)
(backend / ".env").write_text(text)
PY
  fi
}

setup_frontend() {
  require pnpm "Instale com: npm install -g pnpm"
  local modules="$ROOT/frontend/node_modules/.modules.yaml"
  if [ ! -f "$modules" ] || [ "$ROOT/frontend/pnpm-lock.yaml" -nt "$modules" ]; then
    bold "▸ Instalando dependências do frontend"
    (cd "$ROOT/frontend" && pnpm install --frozen-lockfile --config.confirmModulesPurge=false)
  fi
}

port_in_use() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

check_port() {
  if port_in_use "$1"; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN | sed -n '2p' >&2
    fail "A porta $1 ($2) já está em uso. Encerre o processo acima ou use $3=<porta>."
  fi
}

# Prefixa cada linha com o nome do serviço, para os logs não se misturarem.
prefix() {
  awk -v tag="$1" -v color="$2" '{ printf "\033[%sm%s\033[0m %s\n", color, tag, $0; fflush() }'
}

cleanup() {
  trap - INT TERM EXIT
  # Se a saída estiver num pipe que já fechou, um echo não pode abortar a limpeza.
  trap '' PIPE
  # Cada job tem o seu próprio grupo de processos (set -m): mata reload e workers.
  for pid in $(jobs -p); do
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  { echo; bold "▸ Servidores encerrados"; } 2>/dev/null || true
}

check_next_lock() {
  # O Next.js recusa um segundo `next dev` no mesmo projeto, mesmo noutra porta.
  # O próprio Next regista o servidor ativo em .next/dev/lock (PID e URL); é a
  # mesma fonte que ele consulta, independentemente de como o processo arrancou.
  local lock="$ROOT/frontend/.next/dev/lock" pid url
  if [ -f "$lock" ]; then
    pid="$(sed -nE 's/.*"pid":([0-9]+).*/\1/p' "$lock")"
    url="$(sed -nE 's/.*"appUrl":"([^"]+)".*/\1/p' "$lock")"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      fail "Já existe um next dev deste projeto rodando em ${url:-?} (PID $pid). Use-o ou encerre com: kill $pid"
    fi
  fi
}

preflight() {
  require lsof "Necessário para verificar as portas."
  require curl "Necessário para verificar a saúde da API."
  check_port "$BACKEND_PORT" "backend" "BACKEND_PORT"
  check_port "$FRONTEND_PORT" "frontend" "FRONTEND_PORT"
  check_next_lock
}

case "${1:-}" in
  --preflight)
    # Só verifica se dá para subir (usado pelo CI antes de rodar os testes).
    preflight
    exit 0
    ;;
esac

setup_backend
setup_frontend
if [ "${1:-}" = "--setup-only" ]; then
  bold "✔ Ambiente pronto. Rode ./scripts/dev.sh (ou make dev) para subir os servidores."
  exit 0
fi

preflight

set -m
trap cleanup EXIT
# Ctrl+C é o jeito normal de parar: encerra os dois e sai sem erro.
trap 'cleanup; exit 0' INT TERM

# API_LOG=<ficheiro> guarda também o log bruto da API (JSON por linha, sem prefixo).
API_LOG="${API_LOG:-/dev/null}"
: > "$API_LOG"

bold "▸ Subindo API em $API_URL"
(cd "$ROOT/backend" && exec "$PYTHON" -m uvicorn main:app --reload --port "$BACKEND_PORT") 2>&1 \
  | tee -a "$API_LOG" | prefix "[api]" "36" &
API_JOB=$!

for _ in $(seq 1 60); do
  curl -fs -o /dev/null "$API_URL/openapi.json" && break
  kill -0 "$API_JOB" 2>/dev/null || fail "A API não subiu; veja as linhas [api] acima."
  sleep 0.5
done
curl -fs -o /dev/null "$API_URL/openapi.json" || fail "A API não respondeu em 30 s."

# De novo: outro `next dev` pode ter sido iniciado enquanto a API subia.
check_next_lock
bold "▸ Subindo frontend em http://localhost:$FRONTEND_PORT"
# Binário direto (sem `pnpm exec`): subir nunca instala nem remove pacotes.
(cd "$ROOT/frontend" && BACKEND_URL="$API_URL" NEXT_PUBLIC_BACKEND_URL="$API_URL" \
  exec ./node_modules/.bin/next dev --port "$FRONTEND_PORT") 2>&1 | prefix "[web]" "35" &
WEB_JOB=$!

bold "✔ Painel:  http://localhost:$FRONTEND_PORT"
bold "✔ API:     $API_URL/docs"
bold "  Ctrl+C encerra os dois."

# Bash 3.2 (macOS) não tem `wait -n`: vigia os dois e encerra tudo se um cair.
while kill -0 "$API_JOB" 2>/dev/null && kill -0 "$WEB_JOB" 2>/dev/null; do
  sleep 1
done
fail "Um dos servidores parou; encerrando o outro."
