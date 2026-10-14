#!/usr/bin/env bash
# Pipeline local: roda todas as verificações, mostra um resumo e sobe os servidores.
#
#   ./scripts/ci.sh             verificações + resumo; se tudo passar, sobe back e front
#   ./scripts/ci.sh --no-serve  só verificações + resumo (código de saída 1 se algo falhar)
#
# Aceita as mesmas variáveis do scripts/dev.sh (BACKEND_PORT, FRONTEND_PORT,
# DATABASE_URL, API_LOG...). Sem `set -e`: todas as etapas rodam mesmo que uma
# falhe, para o resumo mostrar o quadro completo.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
SERVE=1
[ "${1:-}" = "--no-serve" ] && SERVE=0
TMP_BASE="${TMPDIR:-/tmp}"
LOG_DIR="${TMP_BASE%/}/celso-ci-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$LOG_DIR"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
now() { perl -MTime::HiRes=time -e 'printf "%.1f", time'; }
strip_ansi() { sed $'s/\x1b\\[[0-9;]*[a-zA-Z]//g' "$1"; }

NAMES=()
CODES=()
TIMES=()
DETAILS=()
LOGS=()

# run_stage <nome> <pasta> <parser> <comando...>
run_stage() {
  local name="$1" dir="$2" parser="$3"
  shift 3
  local index=$(( ${#NAMES[@]} + 1 ))
  local log="$LOG_DIR/$index.log"
  echo
  bold "━━━ [$index] $name"
  local started
  started="$(now)"
  (cd "$dir" && "$@") 2>&1 | tee "$log"
  local code=${PIPESTATUS[0]}
  NAMES+=("$name")
  CODES+=("$code")
  TIMES+=("$(perl -e "printf '%.1fs', $(now) - $started")")
  DETAILS+=("$("$parser" "$log" "$code")")
  LOGS+=("$log")
}

# Cada parser resume o log da etapa numa linha para o quadro final.
pytest_summary() {
  local text tests coverage
  text="$(strip_ansi "$1")"
  tests="$(echo "$text" | grep -Eo '[0-9]+ (passed|failed|errors?|skipped)' | paste -sd',' - | sed 's/,/, /g')"
  coverage="$(echo "$text" | awk '/^TOTAL/ {print $NF}')"
  echo "${tests:-sem resultado} · cobertura ${coverage:-?}"
}

vitest_summary() {
  local line
  line="$(strip_ansi "$1" | grep -E '^ +Tests ' | sed -E 's/^ +Tests +//')"
  echo "${line:-sem resultado}"
}

tsc_summary() {
  local errors
  errors="$(strip_ansi "$1" | grep -c 'error TS')"
  if [ "$errors" = "0" ] && [ "$2" = "0" ]; then echo "0 erros de tipo"; else echo "$errors erro(s) de tipo"; fi
}

eslint_summary() {
  local problems
  problems="$(strip_ansi "$1" | grep -Eo '[0-9]+ problems? \([^)]*\)' | tail -1)"
  echo "${problems:-sem problemas}"
}

# 1) Antes de gastar tempo com testes, garante que dá para subir no fim.
if [ "$SERVE" = 1 ]; then
  bold "▸ Verificando se as portas estão livres"
  "$ROOT/scripts/dev.sh" --preflight || {
    echo "  Dica: rode só as verificações com ./scripts/ci.sh --no-serve (ou make check)."
    exit 1
  }
fi

# 2) Ambiente (venv, dependências, .env): idempotente e rápido quando já está pronto.
bold "▸ Preparando o ambiente"
"$ROOT/scripts/dev.sh" --setup-only || exit 1

STARTED="$(now)"

# 3) Verificações. Cores forçadas porque a saída passa pelo tee.
run_stage "Backend · testes + cobertura (pytest)" "$ROOT/backend" pytest_summary \
  "$PYTHON" -m pytest -q --color=yes --cov=app --cov-report=term
run_stage "Frontend · testes (Vitest)" "$ROOT/frontend" vitest_summary \
  env FORCE_COLOR=1 ./node_modules/.bin/vitest run
# `next typegen` gera os tipos de rota (ex.: LayoutProps) que um clone limpo ainda não tem.
run_stage "Frontend · typecheck (tsc)" "$ROOT/frontend" tsc_summary \
  sh -c './node_modules/.bin/next typegen >/dev/null && ./node_modules/.bin/tsc --noEmit --pretty'
run_stage "Frontend · lint (ESLint)" "$ROOT/frontend" eslint_summary \
  ./node_modules/.bin/eslint --color src tests

# 4) Resumo.
TOTAL="$(perl -e "printf '%.1fs', $(now) - $STARTED")"
FAILED=0
echo
bold "━━━ Resumo do CI ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for i in "${!NAMES[@]}"; do
  if [ "${CODES[$i]}" = "0" ]; then
    mark=$'\033[32m✔\033[0m'
  else
    mark=$'\033[31m✖\033[0m'
    FAILED=$((FAILED + 1))
  fi
  printf '  %s  %-40s %7s   %s\n' "$mark" "${NAMES[$i]}" "${TIMES[$i]}" "${DETAILS[$i]}"
done
echo
if [ "$FAILED" -gt 0 ]; then
  printf '\033[31m✖ %d de %d etapas falharam em %s.\033[0m\n' "$FAILED" "${#NAMES[@]}" "$TOTAL"
  for i in "${!NAMES[@]}"; do
    [ "${CODES[$i]}" != "0" ] && echo "  log de \"${NAMES[$i]}\": ${LOGS[$i]}"
  done
  [ "$SERVE" = 1 ] && echo "  Os servidores não foram iniciados. Corrija e rode de novo."
  exit 1
fi
printf '\033[32m✔ %d de %d etapas OK em %s.\033[0m Logs em %s\n' \
  "${#NAMES[@]}" "${#NAMES[@]}" "$TOTAL" "$LOG_DIR"

# 5) Tudo verde: sobe backend e frontend (Ctrl+C encerra os dois).
if [ "$SERVE" = 1 ]; then
  echo
  bold "▸ Tudo verde: subindo os servidores"
  exec "$ROOT/scripts/dev.sh"
fi
