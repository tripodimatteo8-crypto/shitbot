#!/usr/bin/env bash
# Avvio di SolBot con un solo comando: prepara venv, compila la dashboard e lancia il bot.
# Usato anche dal servizio launchd (che lo riavvia dopo crash o riavvio del Mac).
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.claude/local:$PATH"
# nvm (Node e la CLI `claude` installati con nvm non sono nel PATH di launchd)
if [ -s "$HOME/.nvm/nvm.sh" ]; then
  set +u; . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1 || true; set -u
fi
mkdir -p logs data

# 1) .env
if [ ! -f .env ]; then
  cp .env.example .env
  echo "[start] Creato .env da .env.example: aggiungi ANTHROPIC_API_KEY (senza, decide la strategia baseline)."
fi

# 2) Python 3.12 + dipendenze (reinstalla solo se requirements.txt cambia)
PY=""
for c in python3.12 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  echo "[start] Serve Python >= 3.12 (brew install python@3.12)"; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv
fi
REQ_HASH="$(shasum requirements.txt | cut -d' ' -f1)"
if [ "$(cat .venv/.req_hash 2>/dev/null || true)" != "$REQ_HASH" ]; then
  .venv/bin/pip install --upgrade pip -q
  .venv/bin/pip install -r requirements.txt -q
  echo "$REQ_HASH" > .venv/.req_hash
fi

# 3) Dashboard (compila se manca o se i sorgenti sono più recenti della build)
if command -v npm >/dev/null 2>&1; then
  if [ ! -f web/dist/index.html ] || [ -n "$(find web/src web/package.json -newer web/dist/index.html 2>/dev/null | head -1)" ]; then
    echo "[start] Compilo la dashboard…"
    (cd web && npm install --no-audit --no-fund --silent && npm run build --silent) || echo "[start] Build dashboard fallita: il bot parte comunque (API su /api)."
  fi
else
  echo "[start] npm non trovato: dashboard non compilata (brew install node). Il bot parte comunque."
fi

# 4) Avvio. Su macOS `caffeinate -is` impedisce lo sleep finché il bot è in esecuzione.
echo "[start] SolBot su http://127.0.0.1:${PORT:-8787}"
if [ "$(uname)" = "Darwin" ]; then
  exec /usr/bin/caffeinate -is "$ROOT/.venv/bin/python" -m solbot run
else
  exec "$ROOT/.venv/bin/python" -m solbot run
fi
