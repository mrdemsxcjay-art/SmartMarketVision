#!/usr/bin/env bash
# Installation de l'environnement (exécuté une fois, à la création du Codespace).
# Aucun secret n'est demandé ici : sans variables TELEGRAM_*, l'application
# démarre en NOT_CONFIGURED et les alertes restent en file sans être perdues.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "→ dépendances backend (backend/requirements.txt)"
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet -r backend/requirements.txt

echo "→ dépendances + build du dashboard"
( cd frontend && npm ci --silent && npm run build )

echo "→ vérification rapide"
python3 -c "import sys; sys.path.insert(0,'backend'); from app.config import settings; \
print('provider :', settings.market_data_provider, '| telegram :', 'configuré' if settings.telegram_bot_token else 'NOT_CONFIGURED')"
echo "✅ Environnement prêt. Le serveur démarre automatiquement sur le port 8000."
