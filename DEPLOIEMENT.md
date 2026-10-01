# DÉPLOIEMENT HORS ARENA — et configuration du bot Telegram

Ce document répond à deux questions :

1. **comment faire tourner l'aperçu (dashboard + API) en dehors d'Arena** — sur votre machine, votre téléphone, un serveur ou un conteneur ;
2. **comment configurer le bot Telegram** alors qu'il n'est pas configuré aujourd'hui (`TELEGRAM = NOT_CONFIGURED`).

Pourquoi c'est nécessaire : l'aperçu affiché dans Arena est servi par la **sandbox** qui exécute ce projet (`https://<port>-<sandbox>.e2b.app`). Il ne vit que pendant la session : quand la sandbox est recyclée, l'URL tombe. Le projet, lui, est autonome : **un seul processus, un seul port**, API + dashboard React ensemble.

---

## 0. Ce qu'il faut sur la machine

| Besoin | Version | Obligatoire ? |
|---|---|---|
| Python | 3.11+ (testé sur 3.13) | oui |
| Node.js | 20+ | **seulement** si vous reconstruisez le dashboard (code React modifié) |
| Docker | 24+ | optionnel (chemin le plus simple pour un serveur) |
| Polices DejaVu | paquet `fonts-dejavu-core` sur Linux | recommandé : c'est la police des captures PNG (repli automatique sinon) |

Dépendances vérifiées le 2026-10-01 : **`backend/requirements.txt` suffit** — un venv neuf installé depuis ce seul fichier fait passer les **663 tests** et démarre l'application. `Pillow` (moteur de capture de la Phase 7) y a d'ailleurs été **ajouté** pendant cette vérification : il était présent dans l'environnement de développement sans être déclaré, ce qui cassait l'import sur une machine neuve.

---

## 1. Lancer en local (le plus rapide)

Récupérez le dossier du projet depuis Arena (téléchargement du workspace) ou votre dépôt Git, puis :

```bash
cd smart-market-vision
./start.sh                 # port 8000 par défaut
./start.sh 9000            # autre port
```

`start.sh` fait tout : `.env` créé depuis `.env.example` s'il manque, venv `.venv`, dépendances, build du dashboard si absent, puis démarrage. Ouvrez ensuite :

- **Dashboard** : `http://localhost:8000/` (aussi accessible sur `/app/`)
- **API** : `http://localhost:8000/api` · **documentation** : `http://localhost:8000/docs`
- **Santé** : `http://localhost:8000/api/health`

Sans script (commandes équivalentes) :

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r backend/requirements.txt
python3 -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

Le dashboard est servi par le backend : **un seul port à ouvrir**. Si vous modifiez le code React, reconstruisez-le :

```bash
cd frontend && npm ci && npm run build      # régénère frontend/dashboard_build/
```

---

## 2. Y accéder depuis votre téléphone (même réseau Wi-Fi)

```bash
hostname -I | awk '{print $1}'      # ex. 192.168.1.20
```

Ouvrez `http://192.168.1.20:8000/` sur le téléphone. Si ça ne répond pas : pare-feu de la machine (port 8000), ou réseau « invité » qui isole les appareils. Aucune autre configuration n'est nécessaire — le dashboard est déjà mobile-first (portrait et paysage, sans scroll horizontal).

---

## 3. Exposer sur Internet — trois options

### A. Docker (recommandé sur un serveur)

```bash
cp .env.example .env          # remplissez TELEGRAM_* si souhaité (voir §5)
docker compose up -d --build
```

L'image est construite en deux étapes (Node pour le dashboard, Python pour le runtime) et les polices DejaVu sont installées pour que les captures PNG gardent leur rendu validé. `./data` est monté : **la base SQLite et les captures survivent aux redémarrages**.

Pour ne l'écouter qu'en local et ne l'exposer que via un tunnel ou un reverse proxy, remplacez dans `docker-compose.yml` :

```yaml
    ports:
      - "127.0.0.1:8000:8000"
```

### B. Serveur (VPS) avec systemd + nginx

`/etc/systemd/system/smv.service` :

```ini
[Unit]
Description=Smart Market Vision (scanner + dashboard)
After=network-online.target

[Service]
User=smv
WorkingDirectory=/opt/smart-market-vision
EnvironmentFile=/opt/smart-market-vision/.env
ExecStart=/opt/smart-market-vision/.venv/bin/python -m uvicorn app.main:app \
          --app-dir backend --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now smv && systemctl status smv
```

nginx (avec HTTPS via `certbot`) — **et une protection par mot de passe, voir §4** :

```nginx
server {
    listen 443 ssl;
    server_name smv.mondomaine.fr;
    # ssl_certificate ... (certbot)
    location / {
        auth_basic "SMART MARKET VISION";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;      # WebSocket du flux temps réel
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 300s;
    }
}
```

```bash
sudo apt-get install -y apache2-utils && sudo htpasswd -c /etc/nginx/.htpasswd smv
```

Le `proxy_set_header Upgrade` est **indispensable** : sans lui, le flux LIVE tombe et le bandeau reste en `RECONNECTING`.

### C. Tunnel temporaire (test depuis n'importe où, sans serveur)

```bash
# Cloudflare (aucun compte nécessaire pour un tunnel éphémère)
cloudflared tunnel --url http://localhost:8000

# ou ngrok
ngrok http 8000
```

Vous obtenez une URL publique pendant que la commande tourne (pratique pour montrer le dashboard au téléphone). **À réserver au test** : voir §4.

---

## 4. ⚠️ Sécurité — à lire avant d'exposer

- **Le dashboard n'a aucune authentification.** Vérifié dans le code : aucune route ne demande d'identifiant. Qui atteint l'URL voit vos analyses **et** peut appeler `POST /api/telegram/test` (qui, en mode REAL, envoie un vrai message).
- L'application écoute par défaut sur `0.0.0.0` (`API_HOST`). Pour un usage strictement local, mettez `API_HOST=127.0.0.1` dans `.env` et passez par un tunnel SSH :

  ```bash
  ssh -L 8000:127.0.0.1:8000 utilisateur@serveur    # puis http://localhost:8000
  ```

- Sur Internet, protégez toujours : mot de passe nginx (`auth_basic`, §3.B), ou Cloudflare Access, ou VPN. Un tunnel `cloudflared`/`ngrok` public est **ouvert à tous** tant qu'il tourne.
- `CORS_ORIGINS=*` convient en développement. En production, limitez : `CORS_ORIGINS=https://smv.mondomaine.fr`.
- Rappel de conception : le projet **n'exécute aucun ordre** et ne parle à aucun broker. Le pire scénario d'une exposition non protégée reste la fuite de vos analyses et l'envoi de messages sur votre chat — jamais une transaction.

---

## 5. Configurer le bot Telegram (état actuel : `NOT_CONFIGURED`)

Constat honnête : dans le `.env` du projet, `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` sont **vides**. Le mode effectif est donc `NOT_CONFIGURED` : le scanner tourne normalement, les alertes restent `QUEUED` sans perte, **et aucun réseau n'est sollicité**. Rien n'est cassé, il manque seulement deux valeurs que **vous seul(e)** pouvez fournir.

### Étapes

1. **Créer le bot** — Telegram → `@BotFather` → `/newbot` → nom, puis identifiant finissant par `bot`. BotFather renvoie un **jeton** (chiffres `:` lettres).
2. **Démarrer la conversation** — ouvrez votre bot et envoyez `/start`. Un bot ne peut pas écrire le premier : sans ce message, il n'y a pas de « chat » à qui envoyer. (Pour un canal/groupe : ajoutez le bot puis envoyez un message.)
3. **Renseigner `.env`** à la racine du projet :
   ```dotenv
   TELEGRAM_BOT_TOKEN=le-jeton-de-BotFather
   TELEGRAM_CHAT_ID=              # laissez vide pour l'instant
   TELEGRAM_ENABLED=true
   ```
4. **Trouver votre `chat_id`** — l'assistant du projet le fait pour vous, sans jamais afficher le jeton :
   ```bash
   cd backend
   python3 tools/telegram_setup.py --list-chats
   ```
   Il affiche les conversations trouvées, par exemple :
   ```
   ✅ Bot joignable : @mon_scanner_bot (Mon scanner)
   Conversations trouvées (recopiez l'identifiant dans TELEGRAM_CHAT_ID) :
            123456789  Jean (type private)
   ```
   Recopiez l'identifiant dans `TELEGRAM_CHAT_ID`.
5. **Vérifier l'envoi réel** :
   ```bash
   python3 tools/telegram_setup.py --send-test     # vrai message, appel réseau réel
   ```
   ⚠️ Ce test-là court-circuite volontairement le mode DRY_RUN : il sert à valider le jeton. Pour tester **la chaîne complète** (message composé par le moteur, file durable, dispatcher, capture PNG) :
   ```bash
   curl -X POST http://localhost:8000/api/telegram/test
   curl -s http://localhost:8000/api/telegram/history?limit=5
   ```
6. **Passer en envoi réel** — deux variables ne suffisent pas :
   ```dotenv
   TELEGRAM_MODE=REAL
   ```
   puis redémarrez l'application. Vérifiez : `GET /api/telegram/status` → `"mode": "REAL"`.

### Les trois modes, sans ambiguïté

| Mode | Condition | Comportement |
|---|---|---|
| `NOT_CONFIGURED` | une des deux variables manque | alerte `QUEUED`, `attempts=0`, **aucun réseau**, scanner jamais bloqué |
| `DRY_RUN` | variables présentes, `TELEGRAM_MODE` ≠ REAL | message réellement composé, `SENT` **simulé**, aucun appel réseau |
| `REAL` | variables présentes **et** `TELEGRAM_MODE=REAL` | envoi réel (texte + capture PNG de la Phase 7), retry/backoff si échec |

### Ce que vous recevrez

Les alertes ne partent que sur les états notifiables (`CREATED`, `CONFIRMED`, `INVALIDATED`, `EXPIRED`) et **jamais sur `NO_TRADE`** tant que `TELEGRAM_SEND_NO_TRADE=false` (défaut). Message type, sur données réelles :

```
🚨 SMART MARKET VISION
USDCAD · M15
🟢 BUY — OPPORTUNITÉ OBSERVÉE
Confluence 5/10
Score : 8/10
État : CREATED
...
⚠️ Observation uniquement — aucune exécution automatique, aucun ordre.
```

### Hygiène du jeton (non négociable)

- Le jeton vit **uniquement** dans `.env`, qui est déjà exclu par `.gitignore` : ne le collez jamais dans un fichier suivi, un ticket, un écran ou un chat.
- Le projet ne l'affiche nulle part : `/api/telegram/status` renvoie `NOT_SET` ou un aperçu masqué (`123456******`), les logs et les captures ne le contiennent pas (vérifié par tests).
- Si un jeton a fuité : BotFather → `/revoke` → nouveau jeton → mettre à jour `.env` → redémarrer. Rien d'autre à changer.
- Rappel : **je ne vous demanderai jamais ce jeton**, et aucune valeur n'a été écrite dans ce dépôt.

---

## 6. Données, sauvegarde, mise à jour

| Élément | Emplacement | À sauvegarder ? |
|---|---|---|
| Base SQLite (chandelles, détections, confluences, opportunités, alertes) | `data/smart_market_vision.db` | oui (c'est l'historique) |
| Captures PNG réelles (Phase 7) | `data/captures/` | oui si vous voulez la preuve visuelle |
| Configuration | `.env` | oui — **jamais dans Git** |

Mise à jour : `git pull` (ou remplacement du dossier) → `pip install -r backend/requirements.txt` (si le fichier a changé) → `cd frontend && npm ci && npm run build` si le code React a changé → redémarrage. Les données ne sont jamais touchées par une mise à jour.

---

## 7. Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `ModuleNotFoundError: No module named 'uvicorn'` / `'PIL'` | venv non activé, ou dépendances non installées | `source .venv/bin/activate && pip install -r backend/requirements.txt` (Pillow y est désormais déclaré) |
| Dashboard : page blanche | `frontend/dashboard_build/` absent | `cd frontend && npm ci && npm run build` |
| Flux en `RECONNECTING` en boucle derrière nginx | en-têtes WebSocket absents | ajouter `Upgrade`/`Connection` (§3.B) |
| Pas de données de marché | provider injoignable | l'app affiche `DATA UNAVAILABLE` et garde la cause dans les logs (`provider_health` dans `/api/status`) — aucune donnée n'est inventée |
| Pas d'alerte Telegram | mode `NOT_CONFIGURED` ou `DRY_RUN` | `GET /api/telegram/status` : regardez `mode`, `configured`, `queue` |
| `chat not found` | bot jamais démarré dans la conversation, ou mauvais `chat_id` | envoyer `/start` au bot, relancer `--list-chats` |
| Captures sans texte lisible | polices DejaVu absentes | `sudo apt-get install -y fonts-dejavu-core` (déjà dans l'image Docker) |
| L'aperçu Arena ne répond plus | sandbox recyclée | ce document : relancez en local ou en conteneur, les données sont intactes |

---

## 8. Vérifié le 2026-10-01

- venv neuf + `backend/requirements.txt` → **663 tests backend verts**, application démarrée (`/api/health` 200, dashboard 200).
- `./start.sh 8010` sur un venv vierge → health `200`, dashboard `200`, `provider: yahoo`, scanner actif.
- `backend/tools/telegram_setup.py` sans jeton → explique la marche à suivre, code de sortie `0` ; avec un jeton factice → « Unauthorized » et **0 occurrence du jeton** dans la sortie (masqué `123456******`).
- Docker non installé dans l'environnement de développement : le `Dockerfile` et le `docker-compose.yml` n'ont donc **pas** été construits ici — la syntaxe et le YAML ont été vérifiés, et les commandes équivalentes (venv + uvicorn) l'ont été de bout en bout.
