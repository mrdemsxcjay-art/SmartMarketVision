# DÉPLOIEMENT PAR GITHUB — et où mettre le jeton sans fichier `.env`

Ce document répond précisément à deux demandes :

1. **« je ne trouve pas le `.env` »** → avec GitHub, **vous n'avez plus besoin de ce fichier** : le jeton se saisit dans une interface web (§3).
2. **« un dépôt GitHub qui nous délivre un lien d'aperçu »** → trois chemins sont préparés dans ce dépôt, du plus direct au plus permanent (§2).

> Rappel de sécurité, valable pour tout ce document : le jeton Telegram **n'entre jamais dans le dépôt**. Il n'est ni dans un fichier suivi, ni dans un workflow, ni dans un rapport. `.gitignore` refuse explicitement `.env` **et** `.env.*` (sauvegardes comprises). En cas de fuite : BotFather → `/revoke` → nouveau jeton.

---

## 1. Mettre le projet sur GitHub

> **État au 2026-10-01** : le dépôt est **déjà publié** sur
> <https://github.com/mrdemsxcjay-art/SmartMarketVision> (branche `main`, 212 fichiers).
> La CI n'y est pas encore : le jeton de publication n'avait pas la permission *Workflows*.
> Voir `docs/LISEZ_MOI_CI.md` (copies texte des workflows + deux façons de les activer).

Tout est prêt (`.gitignore`, `Dockerfile`, `.github/workflows/ci.yml`, `.devcontainer/`, `render.yaml`). Il ne manque que votre compte GitHub :

```bash
cd smart-market-vision
git init                        # déjà fait ici, sinon à lancer
git add .
git commit -m "SMART MARKET VISION - phases 1 a 8"

# créez un dépôt vide sur github.com (bouton "New repository"), puis :
git remote add origin https://github.com/<votre-compte>/smart-market-vision.git
git push -u origin main
```

Vous pouvez aussi pousser en SSH (`git@github.com:...`) ou avec GitHub Desktop / l'interface web (« upload files »).

**Ce qui part dans le dépôt** : le code, les tests, les rapports, les aperçus (`reports/dashboard/`, versions allégées), la documentation. **Ce qui ne part pas** : `.env`, `.venv/`, `node_modules/`, `frontend/dashboard_build/`, `data/` (base SQLite et captures PNG réelles).

---

## 2. Obtenir un lien d'aperçu — trois options

### Option A — GitHub Codespaces (le plus proche de ce que vous connaissez déjà)

Sur la page du dépôt : bouton vert **Code → Codespaces → Create codespace on main**.

Le Codespace construit l'environnement (dépendances, dashboard, polices DejaVu), **démarre le serveur tout seul** et GitHub ouvre un onglet **PORTS** avec une URL publique du type :

```
https://<codespace>-8000.app.github.dev
```

C'est un aperçu **complet et vivant** : mêmes données réelles, même flux WebSocket, mêmes captures PNG. C'est l'équivalent exact du preview Arena, mais rattaché à votre dépôt GitHub.

Coût : quotas gratuits mensuels d'heures Codespaces (au-delà, facturé). Le Codespace s'arrête après inactivité — mais **l'URL change** à chaque recréation, car le nom du Codespace change.

### Option B — Render (URL fixe, gratuite)

Sur [render.com](https://render.com) : **New + → Blueprint → sélectionnez votre dépôt**. Render lit `render.yaml`, construit le `Dockerfile`, et vous donne une URL stable :

```
https://smart-market-vision.onrender.com
```

- **Avantages** : URL qui ne change jamais, HTTPS, WebSocket pris en charge, `autoDeploy` (chaque `git push` redéploie).
- **Limites honnêtes** : le plan gratuit **met le service en veille** après ~15 min d'inactivité (le premier chargement prend ~30 s), et **n'a pas de disque persistant** — la base SQLite et les captures repartent de zéro à chaque redéploiement (l'historique de marché se reconstruit, rien n'est inventé pour autant). Pour conserver les données : plan payant + le bloc `disk:` déjà rédigé (en commentaire) dans `render.yaml`.
- Railway, Fly.io, Koyeb fonctionnent de la même façon : ils construisent le même `Dockerfile` (le port suit `$PORT` automatiquement).

### Option C — GitHub Pages (interface seule, sans données)

Un workflow `pages.yml` (déclenchement **manuel**) publie le dashboard en statique :

GitHub → onglet **Actions** → *Publier le dashboard (statique)* → **Run workflow** → le lien apparaît dans **Settings → Pages**.

⚠️ **Soyez prévenu** : GitHub Pages ne sert que des fichiers — **aucun backend ne peut y tourner**. Vous verrez donc l'interface complète (panneaux, styles, mobile) mais les appels `/api/...` échoueront : le dashboard affichera honnêtement `DATA UNAVAILABLE` et `RECONNECTING`, jamais de valeur inventée. Pratique pour montrer l'interface ; inutile pour voir les analyses. **Pour un aperçu réel, utilisez A (Codespaces) ou B (Render).**

---

## 3. Mettre le jeton Telegram — sans chercher aucun fichier

Les deux valeurs se saisissent **dans l'interface de la plateforme**, pas dans le dépôt. La configuration du projet lit les variables d'environnement *et* le fichier `.env` : si vous déployez via GitHub, **le fichier `.env` devient facultatif**.

### Sur Render (ou Railway / Fly.io)

Tableau de bord du service → **Environment** → *Add Environment Variable* :

| Clé | Valeur | Remarque |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | *(le jeton de BotFather)* | type **Secret** |
| `TELEGRAM_CHAT_ID` | *(votre identifiant de chat)* | type **Secret** |
| `TELEGRAM_MODE` | `DRY_RUN` d'abord, puis `REAL` | commencez en simulation |

Enregistrez → redéploiement automatique. Vérifiez ensuite :

```
https://votre-app.onrender.com/api/telegram/status
```
→ `"mode": "DRY_RUN"` ou `"REAL"`, et **jamais** le jeton (le champ s'appelle `bot_token_preview` et affiche `NOT_SET` ou `123456******`).

### Sur Codespaces

- **Le plus simple** : ouvrez un terminal du Codespace, créez le `.env` **dans le Codespace** (il n'est pas poussé sur GitHub) :
  ```bash
  nano .env      # puis renseignez TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID
  ```
- **Le plus propre** : github.com → *Settings → Codespaces → Secrets* → ajoutez `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` (portée : votre dépôt). Ils seront disponibles comme variables d'environnement dans chaque Codespace, sans jamais toucher au disque.

### Vérifier que ça marche, dans l'ordre

1. `GET /api/telegram/status` → `mode` attendu : `NOT_CONFIGURED` → `DRY_RUN` → `REAL`.
2. `POST /api/telegram/test` (bouton ou curl) : la route **passe par la file durable** comme une vraie alerte.
3. `GET /api/telegram/history` : l'alerte apparaît avec `mode`, `attempts`, et `capture_id` si une capture existe.

### À propos de votre proposition de m'envoyer le jeton

C'est possible, mais **la méthode par l'interface ci-dessus est meilleure** — et c'est celle que je vous recommande :

- Sur la plateforme, le secret est chiffré, jamais écrit dans un fichier ni dans un dépôt ; vous pouvez le changer sans rien me transmettre.
- Collez-le **dans le chat** : il apparaîtrait dans l'historique de conversation. À éviter.
- Si vous tenez à ce que je le mette en place moi-même, **joignez le fichier `.env` en pièce jointe** dans un message : le contenu d'une pièce jointe n'est pas recopié dans le texte de la conversation, je l'écrirai dans `.env` (déjà exclu de Git) et **je ne l'afficherai jamais** — ni dans un message, ni dans un rapport, ni dans un log.

---

## 4. Après le déploiement : ce qui est vrai dans tous les cas

| Point | Comportement |
|---|---|
| Exécution d'ordres | **aucune** : pas de broker, pas d'API d'exécution, `order_execution: false` |
| Jetons | uniquement dans les variables d'environnement de la plateforme ; jamais dans le dépôt, les logs, le dashboard ou les captures |
| Telegram indisponible | le scanner **continue** : les alertes restent en file (`QUEUED`), rien n'est perdu |
| Marché injoignable | état explicite `DATA UNAVAILABLE`, cause conservée dans `/api/status` → `provider_health` ; aucune donnée inventée |
| Multi-utilisateurs | le dashboard **n'a pas d'authentification** : sur une URL publique, ajoutez une protection (Cloudflare Access, mot de passe du fournisseur, ou restez en réseau privé) |
| Tests | la CI GitHub (`ci.yml`) exécute 663 tests backend + 64 tests frontend sans réseau ni secret |

---

## 5. Fichiers ajoutés pour ce déploiement

| Fichier | Rôle |
|---|---|
| `.github/workflows/ci.yml` | tests backend + frontend à chaque push (aucun secret requis) |
| `.github/workflows/pages.yml` | publication **manuelle** de l'interface sur GitHub Pages |
| `.devcontainer/devcontainer.json` | Codespace prêt à l'emploi : port 8000 auto-transféré, aperçu ouvert automatiquement |
| `scripts/dev_setup.sh` / `dev_start.sh` | installation puis démarrage automatique dans le Codespace |
| `render.yaml` | blueprint Render : Docker, healthcheck `/api/health`, secrets à saisir dans l'interface |
| `Dockerfile` / `docker-compose.yml` | image unique API + dashboard, port `$PORT` ou 8000 |
| `start.sh` | lancement local en une commande |
| `backend/tools/telegram_setup.py` | état Telegram, recherche du `chat_id`, test d'envoi — jeton jamais affiché |
| `DEPLOIEMENT.md` | déploiement hors Arena (local, téléphone, serveur, tunnel) |
