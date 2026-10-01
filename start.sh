#!/usr/bin/env bash
# Lancement local en une commande (hors conteneur).
#
#   ./start.sh              # installe ce qui manque puis démarre sur le port 8000
#   ./start.sh 9000         # autre port
#   PORT=9000 ./start.sh    # équivalent
#
# Le script reste volontairement simple : un venv local, les dépendances
# déclarées, le build du dashboard si nécessaire, puis uvicorn.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-${PORT:-8000}}"
PYTHON="${PYTHON:-python3}"

if [ ! -f .env ]; then
  echo "→ .env absent : copie de .env.example (Telegram restera NOT_CONFIGURED)"
  cp .env.example .env
fi

if [ ! -d .venv ]; then
  echo "→ création de l'environnement virtuel .venv"
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "→ installation des dépendances backend (requirements.txt)"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r backend/requirements.txt

if [ ! -d frontend/dashboard_build ] && [ ! -d frontend/dist ]; then
  echo "→ aucun build du dashboard : construction (nécessite Node 20+)"
  ( cd frontend && npm ci && npm run build )
fi

echo "→ démarrage : http://localhost:${PORT}/  (API : /api, docs : /docs)"
echo "  arrêt : Ctrl+C"
exec python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port "${PORT}"
