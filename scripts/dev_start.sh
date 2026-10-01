#!/usr/bin/env bash
# Démarre le dashboard + l'API sur le port 8000 (relancé à chaque ouverture du
# Codespace). Le port est transféré par GitHub : l'URL d'aperçu est affichée
# dans l'onglet "PORTS" et s'ouvre automatiquement.
set -euo pipefail
cd "$(dirname "$0")/.."

if curl -sf -m 2 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  echo "✅ Le serveur répond déjà sur le port 8000."
  exit 0
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "→ .env créé depuis .env.example (Telegram restera NOT_CONFIGURED tant que les valeurs sont vides)"
fi

LOG=/tmp/smart-market-vision.log
nohup python3 -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 \
  >"$LOG" 2>&1 &
echo "→ démarrage du serveur (journal : $LOG)"

for _ in $(seq 1 60); do
  if curl -sf -m 2 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "✅ Dashboard prêt : ouvrez le port 8000 (onglet PORTS) — http://localhost:8000/"
    exit 0
  fi
  sleep 1
done

echo "❌ Le serveur n'a pas répondu en 60 s. Dernières lignes du journal :"
tail -20 "$LOG"
exit 1
