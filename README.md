# SMART MARKET VISION — phases 1 à 8

Scanner et observateur de marché Forex. **L'application n'exécute jamais d'ordre** :
elle observe, structure, capture et alerte. Aucune connexion broker, aucune gestion de position.

> **Livré** : données réelles (P1) → détection chartiste (P2) → price action (P3) → SMC/ICT (P4)
> → confluence explicable (P5) → opportunités (P6, direction analytique uniquement)
> → captures PNG réelles (P7) → alertes Telegram avec file durable (P8) → dashboard temps réel.
>
> **Démarrage** : `./start.sh` puis <http://localhost:8000/>.
> **Déploiement hors Arena / GitHub / Telegram** : [`DEPLOIEMENT.md`](DEPLOIEMENT.md) et
> [`DEPLOIEMENT_GITHUB.md`](DEPLOIEMENT_GITHUB.md).
> **Rapport final des phases 5 à 8** : [`PHASE5_6_7_8_FINAL_REPORT.md`](PHASE5_6_7_8_FINAL_REPORT.md).

---

## 1. Ce que fait l'application

| Domaine | Phase 1 |
|---|---|
| Données de marché | Forex réel via Yahoo Finance (OHLCV), 10 paires, M5/M15/H1/H4/D1 |
| Structure | pivots (swing high/low) + labels HH / HL / LH / LL + tendance BULLISH / BEARISH / RANGE / UNDEFINED |
| Temps réel | WebSocket `/api/stream` (+ SSE `/api/events`), états LIVE / RECONNECTING / DISCONNECTED |
| Dashboard | mobile-first, chandeliers (Lightweight Charts), zoom, déplacement, portrait et paysage |
| Historique | SQLite (migration PostgreSQL par variable d'environnement) |
| Notifications | interface Telegram prête, **optionnelle** (`NOT_CONFIGURED` si absente) |
| Détections | **aucune** — le dashboard affiche `NO ACTIVE DETECTION` |
| Capture visuelle | contrat de données prêt, rendu **non implémenté** (`CAPTURE_NOT_IMPLEMENTED`) |
| Exécution d'ordre | **impossible** : aucune route, aucune méthode, aucune clé broker |

---

## 2. Stack

* **Backend** : Python 3.13, FastAPI, httpx, SQLAlchemy 2, Pydantic v2 — un seul processus.
* **Frontend** : React 18 + TypeScript + Vite, `lightweight-charts` v4, CSS responsive mobile-first.
* **Base** : SQLite (fichier `data/smart_market_vision.db`).
* **Temps réel** : WebSocket natif FastAPI (SSE en secours).
* **Tests** : pytest + pytest-asyncio (backend), Vitest + Testing Library (frontend).
* **Provider** : Yahoo Finance (`query1/query2.finance.yahoo.com`) — **aucune clé API requise**.

Aucun Kubernetes, aucun microservice, aucune IA externe, aucun abonnement payant.

---

## 2 ter. Phase 3 — moteur Price Action

Moteur déterministe et explicable ajouté **sans toucher** aux fondations Phase 1/2 :

* **9 figures candlestick** (engulfing haussier/baissier, pin bar haussier/baissier, marteau,
  étoile filante, inside bar, outside bar, doji) — chaque mesure est recalculable depuis l'OHLC réel ;
* **contexte structurel mesuré** : impulsion, consolidation, rejet de niveau, cassure manquée
  (le breakout et le retest sont ceux de la Phase 2 — pas de second moteur) ;
* **contexte de niveau** (`BULLISH_ENGULFING_AT_SUPPORT`…) et **confluence informative**, sans
  aucun score ni recommandation ;
* paramètres centralisés et modifiables en ligne (`/api/price-action/params`) ;
* événements `PRICE_ACTION_DETECTED / CONFIRMED / INVALIDATED / EXPIRED` + `FAILED_BREAKOUT`
  sur **l'Event Bus Phase 1/2**, persistés et dédupliqués par bougie ;
* dashboard : section PRICE ACTION + filtres **TOUS / CHARTISTE / PRICE ACTION** et calques graphiques.

Rapport complet : [`PHASE3_REPORT.md`](PHASE3_REPORT.md) · données réelles :
`reports/price_action_real_data.md` · vérification : `scripts/verify_price_action_live.py`.

**Aucun signal de trading** : uniquement DÉTECTÉ / CONFIRMÉ / INVALIDÉ / EXPIRÉ et des faits objectifs.
SMC/ICT reste explicitement hors périmètre (`SMC_ICT_ENGINE = NOT_IMPLEMENTED`).

---

## 2 bis. Phase 2 — moteur de détection chartiste

Le scanner n'observe pas seulement les prix : depuis la Phase 2 il reconnaît des **figures chartistes** avec
des critères mesurables, et le dit honnêtement (aucune figure « qui ressemble », aucune invention de données).

* **Motifs** : Double Top/Bottom, Épaules-Tête-Épaules (et inversée), triangles (ascendant, descendant,
  symétrique), biseaux (ascendant, descendant), rectangle, drapeaux et fanions (haussier/baissier), support,
  résistance, canal, **cassure** et **retest** en tant qu'événements séparés.
* **Cycle de vie** : `DETECTED → BREAKOUT_DETECTED → CONFIRMED` / `INVALIDATED` / `EXPIRED`, plus `RETEST_DETECTED`
  (uniquement après une cassure confirmée). Une même formation garde **une seule identité** (`dedup_key`) du début
  à la fin : le dashboard n'est jamais spamme.
* **Explainability** : chaque détection expose ses mesures (`evidence`), ses pivots (`evidence_points`), ses
  critères pondérés (`confidence_factors`, la confiance est recalculée à partir d'eux) et les paramètres utilisés.
* **Paramètres** : **tous** centralisés dans `backend/app/patterns/params.py` (env `PATTERN_*`), lisibles et
  ajustables à chaud via `GET|PATCH /api/patterns/params`.
* **API** : `/api/detections`, `/api/detections/active`, `/api/detections/history`, `/api/detections/{id}`.
* **Temps réel** : `PATTERN_DETECTED`, `BREAKOUT_DETECTED`, `PATTERN_CONFIRMED`, `PATTERN_INVALIDATED`,
  `PATTERN_EXPIRED`, `RETEST_DETECTED` sur le WebSocket/SSE ; un client qui se reconnecte reçoit l'état courant
  (`DETECTIONS_SNAPSHOT`).
* **Vérification sur données réelles** :
  `cd backend && python3 ../scripts/verify_patterns.py` → rapport dans `reports/patterns_real_data.md`.
  Sur l'instance qui tourne : `python3 scripts/verify_phase2_live.py http://localhost:8000`.
* **Non implémenté (assumé)** : Price Action avancé, SMC/ICT, Order Blocks, FVG, BOS/CHoCH, Liquidity Sweep,
  Telegram réel, exécution d'ordres. `/api/status` les déclare `NOT_IMPLEMENTED`.

Détail complet : `PHASE2_REPORT.md`.

## 3. Démarrage rapide

```bash
# 1. configuration
cp .env.example .env          # aucune modification nécessaire pour démarrer

# 2. backend
cd backend
pip install -r requirements.txt
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000   # sans --reload
# (script equivalent : ./backend/run.sh)
#    -> API      http://localhost:8000/api
#    -> Swagger  http://localhost:8000/docs
#    -> Dashboard http://localhost:8000/

# 3. frontend (uniquement si vous modifiez le code React)
cd ../frontend
npm install
npm run build                 # produit dashboard_build/, servi automatiquement par FastAPI à /
# ou en développement avec rechargement à chaud :
npm run dev                   # http://localhost:5173 (proxy /api -> :8000)
```

### Accès depuis un téléphone (même réseau Wi‑Fi)

1. Lancer l'API avec `--host 0.0.0.0` (par défaut dans `.env`).
2. Trouver l'IP locale de la machine :

```bash
ip addr show | grep "inet " | grep -v 127.0.0.1     # Linux
ipconfig getifaddr en0                              # macOS
```
3. Sur le téléphone, ouvrir `http://<IP_LOCALE>:8000/`.
   Le WebSocket utilise la même origine que la page : rien d'autre à configurer.
4. Ajouter la page à l'écran d'accueil (Safari : Partager → Sur l'écran d'accueil) pour un
   affichage plein écran.

---

## 4. Endpoints

| Méthode | Route | Description |
|---|---|---|
| GET | `/api/health` | vivacité + configuration (sans secret) |
| GET | `/api/ready` | état base / provider / scanner |
| GET | `/api/symbols` | instruments surveillés + timeframes |
| GET | `/api/market/{symbol}?timeframe=M15` | snapshot (prix, variation, état marché) |
| GET | `/api/candles/{symbol}/{timeframe}?limit=300` | bougies OHLCV réelles |
| GET | `/api/structure/{symbol}/{timeframe}` | pivots + labels + tendance |
| GET | `/api/market-status` | sessions de trading (horloge, pas les prix) |
| GET | `/api/status` | carte système complète du dashboard |
| GET | `/api/detections` | détections chartistes actives + suivies |
| GET | `/api/price-action` | détections Price Action (+ `/structure`, `/history`, `/confluence`, `/params`) |
| GET | `/api/events/recent` | derniers événements réels |
| GET | `/api/database/coverage` | couverture des bougies stockées |
| GET | `/api/telegram/status` | état du canal, sans secret |
| POST | `/api/telegram/test` | envoi de test si configuré, sinon `NOT_CONFIGURED` |
| GET | `/api/capture/status` | capacité de capture visuelle |
| WS | `/api/stream?symbol=&timeframe=` | flux temps réel (MarketEvent) |
| GET | `/api/events?symbol=&timeframe=` | flux SSE (secours) |

**Contrat d'erreur** : jamais de prix inventé. Si le provider échoue :
* `/api/market/*` → HTTP 200 avec `data_state: "DATA_UNAVAILABLE"` et `price: null` ;
* `/api/candles/*` et `/api/structure/*` → HTTP 503 `{"error": "DATA_UNAVAILABLE", "cause": "..."}`.

---

## 5. Tests

```bash
cd backend  && python3 -m pytest tests/ -q      # 401 tests (Phase 1 + 2 + 3)
cd frontend && npm test                         # 29 tests
cd ..       && python3 scripts/verify_live.py http://localhost:8000   # critères de validation (données réelles)
```

**Restauration après un recyclage de l'environnement, scripts de lancement et dépendances** :
voir [`RESTAURATION.md`](RESTAURATION.md). Aucun secret n'est requis pour démarrer.

Le script `scripts/verify_live.py` interroge l'API en fonctionnement et vérifie les
critères de validation de la phase (bougies réelles, absence de bougie future, cohérence
OHLC, alignement sur la grille du timeframe, structure, temps réel, validations, persistance).

---

## 6. Architecture

```
backend/app/
├── config.py            configuration .env + résolution des chemins
├── logging_conf.py      logs + masquage des secrets
├── instruments.py       catalogue d'instruments (ajouter une paire = 1 ligne)
├── container.py         graphe de services (remplaçable en test)
├── main.py              application FastAPI + montage du dashboard
├── api/                 health, market, system, stream (WebSocket + SSE)
├── providers/
│   ├── base.py          interface MarketDataProvider
│   ├── yahoo.py         provider réel (sans clé API)
│   ├── registry.py      sélection du provider
│   └── errors.py        erreurs typées (cause conservée)
├── schemas/             market, structure, events (MarketEvent, PatternDetection)
├── services/
│   ├── market_service.py  provider + cache + persistance + qualité
│   ├── structure.py       pivots, HH/HL/LH/LL, tendance
│   ├── scanner.py         boucle de fond (données réelles uniquement)
│   ├── events.py          bus d'événements asyncio
│   ├── quality.py         contrôles de cohérence (sans jamais modifier les prix)
│   ├── telegram.py        TelegramNotifier (send_message / send_image)
│   └── visual_capture.py  contrat de capture (rendu non implémenté)
└── db/                  modèles + repositories (candles, events, detections, scanner_runs)

frontend/src/
├── App.tsx              orchestration + rechargement sur événements live
├── api/client.ts        client REST typé
├── hooks/useMarketStream.ts  WebSocket + reconnexion + états LIVE/RECONNECTING/DISCONNECTED
├── components/          Header, Selectors, ChartPanel, Panels
└── styles/app.css       mobile-first (portrait, paysage, safe-area iPhone)
```

### Ajouter une paire

1. Ajouter l'entrée dans `backend/app/instruments.py` (`CATALOG`).
2. L'ajouter à `WATCHLIST` dans `.env`.

Aucune autre modification n'est nécessaire (API, scanner, dashboard suivent).

### Migrer vers PostgreSQL

Remplacer `DATABASE_URL` par `postgresql+psycopg://…` : les modèles SQLAlchemy n'utilisent
aucun type spécifique à SQLite.

---

## 7. Ce qui n'est PAS implémenté (assumé, Phase 1)

* moteurs de détection chartiste / price action / SMC-ICT (BOS, CHoCH, order blocks, FVG, liquidité) ;
* génération d'image du graphique au moment d'une détection (seul le contrat de données existe) ;
* envoi automatique de détections sur Telegram (l'interface `send_message` / `send_image` est prête) ;
* calendrier des jours fériés (le statut marché suit le planning hebdomadaire 24×5) ;
* authentification/ multi-utilisateur (usage personnel, réseau local).

L'application ne place, ne modifie et ne ferme **aucun ordre** : elle n'en a pas la capacité technique.
