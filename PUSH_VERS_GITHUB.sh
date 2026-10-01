#!/usr/bin/env bash
# Publie ce projet sur VOTRE dépôt GitHub.
#
#   ./PUSH_VERS_GITHUB.sh https://github.com/<compte>/smart-market-vision.git
#   ./PUSH_VERS_GITHUB.sh git@github.com:<compte>/smart-market-vision.git
#
# Le script ne demande ni jeton, ni mot de passe GitHub : c'est votre Git local
# qui s'authentifie (navigateur, trousseau macOS, GCM, ou clé SSH). Il vérifie
# surtout que rien de sensible ne part dans le dépôt.
set -euo pipefail
cd "$(dirname "$0")"

REMOTE_URL="${1:-}"
if [ -z "$REMOTE_URL" ]; then
  echo "Usage : ./PUSH_VERS_GITHUB.sh <url-du-depot-github>"
  echo "Exemple : ./PUSH_VERS_GITHUB.sh https://github.com/mon-compte/smart-market-vision.git"
  exit 2
fi

# 1) .git est-il initialisé ?
if [ ! -d .git ]; then
  echo "→ initialisation du dépôt local"
  git init -q
  git branch -M main
fi

# 2) contrôle de sécurité : aucun secret ne doit être suivi par Git
echo "→ contrôle : aucun .env ni jeton suivi par Git"
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "❌ .env est suivi par Git : arrêt immédiat."
  echo "   Corrigez avec : git rm --cached .env  (le fichier reste sur le disque)"
  exit 1
fi
if git grep -I -l -E 'bot[0-9]{6,}:[A-Za-z0-9_-]{20,}' -- . 2>/dev/null | grep -v '\.env\.example'; then
  echo "❌ Un jeton Telegram semble présent dans un fichier suivi ci-dessus : arrêt immédiat."
  exit 1
fi
echo "  ✅ rien de sensible détecté"

# 3) commit
if git rev-parse HEAD >/dev/null 2>&1; then
  echo "→ dépôt déjà committé"
else
  echo "→ premier commit"
  git add -A
  git -c user.name="${GIT_AUTHOR_NAME:-Smart Market Vision}" \
      -c user.email="${GIT_AUTHOR_EMAIL:-smv@local}" \
      commit -q -m "SMART MARKET VISION - phases 1 a 8 (confluence, opportunites, captures, Telegram)"
fi

# 4) remote + push
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi
echo "→ envoi vers $REMOTE_URL"
git push -u origin "$(git branch --show-current)"

cat <<'MESSAGE'

✅ Dépôt publié.

Pour obtenir un lien d'aperçu :
  • Aperçu complet (le plus rapide) : GitHub → Code → Codespaces → Create codespace on main
    Le serveur démarre seul ; l'URL s'affiche dans l'onglet PORTS.
  • URL fixe : render.com → New + → Blueprint → sélectionnez ce dépôt (lit render.yaml).
  • Interface seule : Actions → « Publier le dashboard (statique) » → Run workflow.

Pour Telegram, saisissez TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID dans l'interface de
la plateforme (Render → Environment ; Codespaces → Settings → Secrets).
Le fichier .env n'est pas nécessaire et n'est jamais envoyé sur GitHub.
MESSAGE
