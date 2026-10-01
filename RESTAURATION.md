# RESTAURATION & LANCEMENT — procédure reproductible

Ce document garantit qu'après un recyclage de l'environnement (sandbox redémarrée, processus tués,
paquets hors projet effacés), le projet est restauré **uniquement à partir des fichiers du dépôt**,
sans dépendre d'une installation manuelle précédente.

Tout ce qui suit a été vérifié : un venv neuf créé avec `backend/requirements.txt` seul lance
**401 tests backend** verts, et un `npm ci` avec `frontend/package-lock.json` seul lance
**27 tests frontend** verts.

---

## 1. Lancement normal (aucune installation manuelle)

```bash
# 1. configuration (aucun secret requis : .env.example suffit)
cp .env.example .env

# 2. backend + dashboard
cd backend
pip install -r requirements.txt
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000     # SANS --reload
#    -> API       http://localhost:8000/api
#    -> Swagger   http://localhost:8000/docs
#    -> Dashboard http://localhost:8000/
```

Script équivalent fourni : `backend/run.sh` (mêmes valeurs, sans `--reload`, `exec` pour que le
signal d'arrêt atteigne uvicorn).

```bash
./backend/run.sh                                   # variables API_HOST / API_PORT surchargeables
```

> **Pas de `--reload` dans le lancement prévu.** Le rechargement à chaud est réservé au développement
> frontend (`npm run dev`) et n'est jamais utilisé pour le serveur de production/validation : cela
> évite tout redémarrage en boucle pendant une session.

Le dashboard est servi **statiquement** par FastAPI depuis `frontend/dashboard_build/`
(repli : `frontend/dist/`). Aucun serveur Node n'est nécessaire à l'exécution.

## 2. Frontend — uniquement si le code React change

```bash
cd frontend
npm ci                # restauration exacte depuis package-lock.json
npm run build         # -> dashboard_build/ (servi automatiquement par FastAPI à /)
npm test              # 27 tests
```

Développement avec rechargement à chaud : `npm run dev` (Vite sur :5173, proxy `/api` → :8000).

## 3. Procédure après recyclage de l'environnement

Symptômes : le preview ne répond plus, `/api/health` renvoie `000`, `uptime` vaut « 0 min »,
`ModuleNotFoundError: No module named 'fastapi'`.

```bash
# 1. constater
curl -s -m 5 http://127.0.0.1:8000/api/health     # 000 = serveur absent
uptime                                            # "up 0 min" = sandbox recyclée

# 2. restaurer le runtime backend (déclaré, jamais manuel)
cd backend && pip install -r requirements.txt

# 3. restaurer le runtime frontend (uniquement si le build doit être régénéré)
cd ../frontend && npm ci && npm run build

# 4. redémarrer proprement
cd ../backend && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 5. vérifier
curl -s -m 5 http://127.0.0.1:8000/api/health     # doit renvoyer status: ok
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/    # 200

# 6. relancer les tests
cd backend  && python3 -m pytest tests/ -q        # 663 passed (P1->P8)
cd frontend && npm test -- --run                  # 63 passed

# 7. rejouer la chaîne complète P5->P8 sur données réelles (base temporaire)
cd backend && python3 tools/live_chain.py --test-alert

# 8. reprendre au dernier bloc validé (voir PHASE5_6_7_8_FINAL_REPORT.md) — ne jamais repartir de zéro
```

Coût mesuré : ~5 s pour le backend, ~10 s pour `npm ci` + build.

Validation navigateur P5->P8 après recyclage : `python3 -m playwright install chromium-headless-shell`
puis les bibliothèques système du §5 (mêmes commandes `apt-get`) — sans elles Chromium sort en
code 127.

## 4. Dépendances : ce qui est déclaré, ce qui est optionnel

| Besoin | Déclaré dans | Restauration |
|---|---|---|
| Runtime backend (FastAPI, uvicorn, httpx, pydantic, SQLAlchemy…) | `backend/requirements.txt` | `pip install -r requirements.txt` |
| `starlette`, `websockets` | dépendances **transitives** de `fastapi` et `uvicorn[standard]` | automatique |
| Tests backend (`pytest`, `pytest-asyncio`) | `backend/requirements.txt` (section test-only) | automatique |
| Frontend (React, lightweight-charts, Vite, Vitest, TypeScript, jsdom, Testing Library) | `frontend/package.json` + `package-lock.json` | `npm ci` |
| **Validation navigateur (optionnelle)** : `playwright` + bibliothèques Chromium | hors projet, **non requis pour démarrer** | voir §5 |

Aucune dépendance **essentielle** du projet ne repose sur une installation manuelle non déclarée :
c'est le résultat du test « venv neuf + requirements.txt » (§1).

Rappel mesuré le 2026-10-01 : après un recyclage, `pip install -r requirements.txt` +
`python3 -m playwright install chromium-headless-shell` + les 12 bibliothèques du §5 suffisent à
rejouer la suite complète (663 tests), les contrôles navigateur et `tools/live_chain.py`.

## 5. Optionnel — validation navigateur réelle (§23)

Ces outils ne sont nécessaires **que** pour rejouer `smv_phase3_browser.py`. Ils ne sont pas
requis pour démarrer, tester ou utiliser l'application.

```bash
pip install playwright
python3 -m playwright install chromium-headless-shell
# bibliothèques système manquantes sur une image Debian minimale (sans sudo) :
mkdir -p /tmp/syslibs && cd /tmp/syslibs
apt-get download libnspr4 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libcups2t64
apt-get download libatk1.0-0t64 libatspi2.0-0t64                    # noms trixie
curl -sfLO https://deb.debian.org/debian/pool/main/n/nss/libnss3_3.87.1-1+deb12u2_amd64.deb
curl -sfLO https://deb.debian.org/debian/pool/main/a/alsa-lib/libasound2_1.2.8-1+b1_amd64.deb
for f in *.deb; do dpkg-deb -x "$f" /tmp/syslibs; done
export LD_LIBRARY_PATH=/tmp/syslibs/usr/lib/x86_64-linux-gnu
```

## 6. Secrets

**Aucun secret n'est nécessaire pour démarrer.** `.env.example` est fonctionnel tel quel :
provider de marché sans clé, Telegram non configuré (`TELEGRAM = NOT_CONFIGURED`).
`.env` est ignoré par git ; aucun jeton n'est affiché dans les logs ni dans le dashboard.

## 7. Base de données

`DATABASE_URL=sqlite+pysqlite:///data/smart_market_vision.db` : un chemin relatif est résolu depuis
la **racine du projet**, donc le même fichier est utilisé quel que soit le répertoire courant.
Le dossier et le fichier sont créés automatiquement au premier démarrage ; l'historique de marché
réel est reconstruit par le scanner s'il manque. Les `.db` ne sont pas versionnés (`.gitignore`).

## 8. Périmètre

Cette procédure ne modifie **aucune** logique métier : elle ne fait que restaurer des dépendances,
lancer le serveur, le vérifier et exécuter les tests. Phase 1 et Phase 2 ne nécessitent aucune
modification.
