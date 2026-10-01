# SMART MARKET VISION — Rapport de fin de PHASE 1

**Date d'exécution** : 2026-09-30 (Europe/Paris) · **Environnement** : développement
**Périmètre** : fondation, données Forex réelles, dashboard live mobile-first.
**Aucune détection, aucun ordre, aucune donnée fictive.**

---

## 1. Fichiers créés

### Backend (Python / FastAPI) — 5 918 lignes (application + tests)

| Fichier | Rôle |
|---|---|
| `backend/app/main.py` | application FastAPI, cycle de vie, montage du dashboard, gestion d'erreurs JSON |
| `backend/app/config.py` | configuration `.env` (pydantic-settings), résolution du chemin SQLite, snapshot sans secret |
| `backend/app/logging_conf.py` | logs + filtre de masquage (token Telegram, identifiants d'URL) |
| `backend/app/instruments.py` | catalogue de 21 instruments + normalisation de symbole |
| `backend/app/container.py` | graphe de services (injectable en test) |
| `backend/app/api/health.py` | `/api/health`, `/api/ready` |
| `backend/app/api/market.py` | `/api/symbols`, `/api/market/{symbol}`, `/api/candles/...`, `/api/structure/...`, `/api/market-status`, `/api/instruments/{symbol}` |
| `backend/app/api/system.py` | `/api/status`, `/api/detections`, `/api/events/recent`, `/api/database/coverage`, `/api/telegram/status`, `/api/telegram/test`, `/api/capture/status` |
| `backend/app/api/stream.py` | WebSocket `/api/stream`, SSE `/api/events`, `/api/stream/status` |
| `backend/app/api/deps.py` | injection du conteneur (HTTP et WebSocket) |
| `backend/app/providers/base.py` | interface abstraite `MarketDataProvider` |
| `backend/app/providers/yahoo.py` | provider réel Yahoo Finance + provider `disabled` (mode « pas de flux ») |
| `backend/app/providers/registry.py` | sélection du provider par `MARKET_DATA_PROVIDER` |
| `backend/app/providers/errors.py` | erreurs typées (`ProviderTimeout`, `ProviderRateLimited`, `UnknownSymbol`…) conservant la cause |
| `backend/app/schemas/market.py` | `Candle`, `CandleSeries`, `QuoteSnapshot`, `MarketStatus`, `DataState`, `Timeframe` |
| `backend/app/schemas/structure.py` | `SwingPoint`, `SwingLabel`, `StructuralTrend`, `StructureAnalysis` |
| `backend/app/schemas/events.py` | `MarketEvent`, `PatternDetection` (contrat des phases futures), `DetectionsResponse` |
| `backend/app/services/market_service.py` | provider + cache TTL + persistance + repli « stale » signalé |
| `backend/app/services/quality.py` | contrôles de cohérence (OHLC, timestamps, trous) **sans modifier les prix** |
| `backend/app/services/cache.py` | cache mémoire TTL par timeframe |
| `backend/app/services/structure.py` | pivots, labels HH/HL/LH/LL, classification de tendance |
| `backend/app/services/scanner.py` | boucle de fond : lit, structure, publie, persiste |
| `backend/app/services/events.py` | bus d'événements asyncio (multi-abonnés, thread-safe) |
| `backend/app/services/telegram.py` | `TelegramNotifier` : `send_message()`, `send_image()`, états `CONFIGURED`/`NOT_CONFIGURED` |
| `backend/app/services/visual_capture.py` | contrat de capture (contexte complet, rendu non implémenté) |
| `backend/app/db/base.py`, `models.py`, `repository.py` | SQLite + 4 repositories (candles, events, detections, scanner_runs) |
| `backend/tests/*` (6 fichiers + conftest) | 144 tests |
| `backend/requirements.txt`, `pytest.ini`, `run.sh` | dépendances et lancement |

### Frontend (React + TypeScript + Vite) — 2 090 lignes

| Fichier | Rôle |
|---|---|
| `frontend/src/App.tsx` | orchestration, chargement, rafraîchissement piloté par les événements live |
| `frontend/src/api/client.ts` | client REST typé + `ApiError` (code + message backend) |
| `frontend/src/hooks/useMarketStream.ts` | WebSocket, reconnexion exponentielle, états LIVE / RECONNECTING / DISCONNECTED |
| `frontend/src/components/Header.tsx` | titre, statut LIVE, dernier événement, provider |
| `frontend/src/components/Selectors.tsx` | sélecteur de paire (chips) et de timeframe (segments), cibles tactiles ≥ 42 px |
| `frontend/src/components/ChartPanel.tsx` | chandeliers + API d'overlay réservée aux phases suivantes |
| `frontend/src/components/Panels.tsx` | résumé marché, structure, statut données, détections, pied de page |
| `frontend/src/types/market.ts` | contrats TypeScript alignés sur le backend |
| `frontend/src/styles/app.css` | mobile-first, portrait/paysage, safe-area iPhone |
| `frontend/src/test/*` | 10 tests Vitest + Testing Library |
| `frontend/vite.config.ts`, `tsconfig.json`, `package.json`, `index.html` | build et tests |

### Racine et outillage

| Fichier | Rôle |
|---|---|
| `.env.example` | 30 variables documentées (provider, cache, scanner, watchlist, Telegram…) |
| `.env` | copie locale de travail (ignorée par git) |
| `.gitignore` | exclut secrets, `node_modules`, `dist/`, base SQLite |
| `scripts/verify_live.py` | vérification des critères de validation sur l'API en fonctionnement (42 contrôles) |
| `README.md` | installation, endpoints, architecture, accès téléphone |
| `PHASE1_REPORT.md` | ce rapport |

---

## 2. Architecture

Un **seul processus** fait tout : API REST + WebSocket/SSE + scanner de fond + service du dashboard.
Communication React ↔ FastAPI par REST (état) et WebSocket (temps réel), sur la **même origine**
(aucune URL de backend à saisir, donc fonctionne tel quel depuis un téléphone).

```
Scanner (15 s) ──► MarketService ──► YahooProvider (réseau)
                        │  ├─ cache TTL par timeframe
                        │  ├─ contrôles qualité (jamais de modification des prix)
                        │  └─ persistance SQLite (candles, events)
                        ▼
                   EventBus (asyncio, multi-abonnés)
                        ▼
        WebSocket /api/stream  +  SSE /api/events
                        ▼
              Dashboard React (mobile-first)
```

Décisions structurantes :

* **Aucune donnée inventée** : le provider lève une erreur typée, l'API renvoie
  `DATA_UNAVAILABLE` avec `price: null`, l'UI affiche un état explicite. Le cache n'est
  réutilisé que s'il contient de **vraies** données déjà récupérées, et il est alors marqué `STALE`.
* **Structure repaint-free** : un pivot n'est confirmé qu'après `right` bougies suivantes ; la
  bougie en formation est exclue par défaut (`include_forming=false`).
* **Sécurité par conception** : pas de clé broker, pas de méthode d'ordre, filtre de logs qui
  masque le token Telegram, `/api/status` n'exposant que des booléens de présence.
* **Migration PostgreSQL** : une seule variable d'environnement.

---

## 3. Provider utilisé

**Yahoo Finance** — endpoint public `https://query2.finance.yahoo.com/v8/finance/chart/{PAIR}=X`
(non documenté, lecture seule, **aucune clé API**, aucun abonnement payant). Repli automatique sur
`query1`, rotation de `User-Agent` et de host en cas de `429`, 3 tentatives avec back-off.

Comportement réel mesuré (2026-09-30) et **traité explicitement** :

| Observation réelle | Traitement appliqué |
|---|---|
| Dernière bougie estampillée à la seconde courante (ex. `23:04:59`) pour la période en cours | fusionnée dans la bougie alignée (`23:00`) : open et horodatage conservés, close = dernier prix, high/low étendus — **aucun prix inventé** |
| Bougies avec décalage de 1 s (`23:05:01`) | recalées sur la grille (± 5 s) et signalées dans `quality_warnings` |
| Bougies journalières à minuit de la place (décalage 1 h au changement d'heure) | conservées telles quelles, offsets de grille signalés |
| Bougies nulles (week-ends, jours fériés) | supprimées, comptées dans `quality_warnings` |
| 10 barres D1 sur 250 incohérentes de 0,27 à 2,74 pip (artefact de la source) | **conservées sans modification**, signalées dans `quality_warnings` et dans la vérification live |

Santé mesurée pendant la session : **47 requêtes, 0 échec, latence moyenne 44 ms**.

Un second provider `disabled` est fourni : il ne renvoie aucun prix (utile pour valider le chemin
`DATA UNAVAILABLE`). Alternatives évaluées : Stooq (protégé par anti-bot), ECB SDW/ER-API
(quotidien seulement, pas d'OHLC intraday), Twelve Data (clé `demo` limitée à certains symboles).

---

## 4. Endpoints livrés

| Méthode | Route | État |
|---|---|---|
| GET | `/api/health` | ✅ testé |
| GET | `/api/ready` | ✅ testé |
| GET | `/api/symbols` | ✅ testé |
| GET | `/api/market/{symbol}?timeframe=` | ✅ testé |
| GET | `/api/candles/{symbol}/{timeframe}?limit=` | ✅ testé |
| GET | `/api/structure/{symbol}/{timeframe}` | ✅ testé |
| GET | `/api/market-status` | ✅ testé |
| GET | `/api/status` | ✅ testé |
| GET | `/api/detections` | ✅ testé (toujours `NO ACTIVE DETECTION`) |
| GET | `/api/events/recent` | ✅ testé |
| GET | `/api/database/coverage` | ✅ testé |
| GET | `/api/telegram/status` | ✅ testé |
| POST | `/api/telegram/test` | ✅ testé (`NOT_CONFIGURED` sans variables) |
| GET | `/api/capture/status` | ✅ testé |
| GET | `/api/instruments/{symbol}` | ✅ testé |
| WS | `/api/stream?symbol=&timeframe=` | ✅ testé (tests + navigateur réel) |
| GET | `/api/events` (SSE) | ✅ testé (générateur ASGI + `curl -N` sur serveur réel) |
| GET | `/api/stream/status` | ✅ testé |

Documentation interactive : `http://<hôte>:8000/docs`.

---

## 5. Tests

| Suite | Nombre | Résultat |
|---|---|---|
| Backend `pytest` | **144** | **144 réussis, 0 échec** (8,7 s) |
| Frontend `vitest` | **10** | **10 réussis, 0 échec** (1,5 s) |
| **Total automatisé** | **154** | **154 réussis** |
| Vérification live `scripts/verify_live.py` | 44 | **42 réussis, 2 avertissements, 0 échec** |

Répartition backend : `test_api.py` 44 · `test_provider.py` 25 · `test_structure.py` 21 ·
`test_services.py` 20 · `test_stream.py` 20 · `test_security.py` 14.

Couverture des exigences :

* **provider** : parsing réel, limite, OHLC, alignement, fusion des barres partielles, doublons,
  bougies futures, payload vide, erreur amont, `429`, `timeout`, `5xx`, retry réussi, santé,
  symbole/timeframe inconnus, horloge marché (6 cas hebdomadaires dont vendredi soir et dimanche soir) ;
* **structure** : swing highs/lows, HH/HL/LH/LL, bullish, bearish, range, undefined, pivots égaux,
  index de confirmation, bougies clôturées uniquement, absence totale de vocabulaire SMC/ICT ;
* **API** : chaque endpoint, 422 sur symbole/timeframe/limite invalides, contrat `503 DATA_UNAVAILABLE` ;
* **WebSocket/SSE** : connexion, `hello`, réception d'une mise à jour, filtrage par symbole,
  déconnexion libérant l'abonné, **reconnexion**, heartbeat, abonné lent sans blocage du scanner ;
* **sécurité** : masquage du token dans les logs et les réponses, `NOT_CONFIGURED` sans variables,
  aucune route d'ordre/exécution/position, méthodes HTTP limitées à GET/POST ;
* **frontend** : chargement, sélection paire, sélection timeframe, graphique monté,
  états LIVE / RECONNECTING, mise à jour du prix par événement, `DATA UNAVAILABLE`.

---

## 6. Critères de validation (§17)

| # | Critère | État | Preuve |
|---|---|---|---|
| 1 | Données réellement récupérées | ✅ | 200 bougies × 5 timeframes × 2 paires vérifiées, 6 203 bougies en base, 47 requêtes provider / 0 échec |
| 2 | Timestamps cohérents | ✅ | croissants, sans doublon, alignés sur la grille du timeframe (offsets DST documentés) |
| 3 | Aucune bougie future | ✅ | contrôle `futures=0` dans la vérification live ; filtre dans le provider + test dédié |
| 4 | OHLC cohérents | ⚠️ | intraday : écart max < 0,09 pip (sous la tolérance 0,2 pip) ; **D1** : 8 barres/250 à 0,27–2,74 pip = artefact de la source, conservé tel quel et signalé (avertissement documenté, pas un échec déguisé) |
| 5 | Dashboard sur desktop | ✅ | rendu vérifié en navigateur réel (Chromium) |
| 6 | Dashboard sur mobile | ✅ | 390×844 et 844×390 en navigateur réel, captures ci-dessous |
| 7 | Graphique fonctionnel | ✅ | canvas réellement peint (12 752 px non-fond), zoom/déplacement natifs Lightweight Charts |
| 8 | Changement de paire | ✅ | clic USDJPY → prix 157,381, en-tête `USDJPY H1` (navigateur réel) + test unitaire |
| 9 | Changement de timeframe | ✅ | clic H1 → requête `/api/candles/EURUSD/H1`, en-tête mis à jour + test unitaire |
| 10 | Temps réel | ✅ | WebSocket réel sur le serveur : `MARKET_UPDATE EURUSD 1.13417` sans rechargement |
| 11 | États CONNECTED / RECONNECTING / DISCONNECTED | ✅ | LIVE observé en navigateur, RECONNECTING après fermeture socket (test), DISCONNECTED par watchdog 45 s |
| 12 | API répond correctement | ✅ | 18 routes, OpenAPI complet, erreurs JSON normalisées |
| 13 | Tests passent | ✅ | 154/154 automatisés + 42/44 live (2 avertissements D1) |
| 14 | Aucune donnée fictive en production | ✅ | aucun générateur de prix dans `backend/app/` (uniquement dans `tests/`) ; `disabled` provider explicite |
| 15 | Aucun ordre exécutable | ✅ | aucune route/méthode d'ordre, `order_execution=false` exposé, test dédié qui parcourt toutes les routes |

---

## 7. Problèmes rencontrés et résolus

1. **Yahoo renvoie HTTP 429 sur certains `User-Agent`** (un UA desktop complet ou un UA d'outil sont
   refusés alors que `Mozilla/5.0` passe). → rotation host + UA sur les tentatives, 0 échec après correction.
2. **Barres partielles non alignées** (`23:04:59` pour la période M15 en cours) : elles créaient une
   bougie fantôme et désalignaient le graphique. → fusion contrôlée + note dans `quality_warnings`.
3. **`str(Timeframe.M15)` renvoie `"Timeframe.M15"`** en Python 3.11+ → un helper `as_timeframe()` unique
   remplace tous les `str(...).upper()` (bug réellement détecté par le smoke test, corrigé partout).
4. **Événements perdus en test** : le bus global était utilisé par les routes au lieu du bus du conteneur,
   et les files asyncio n'étaient pas sûres entre boucles. → bus lié au conteneur + livraison
   `call_soon_threadsafe` quand l'appel vient d'un autre thread.
5. **Chemin SQLite dépendant du répertoire courant** (deux bases créées). → résolution du chemin
   relatif par rapport à la racine du projet.
6. **Crash réel du dashboard** : `new Date('2026-09-29T23:15:00+00:00').toISOString()` levait
   `RangeError: Invalid time value` (timestamp `candle_time` avec `+00:00`). → parsing robuste
   `parseTimestamp()` + test de non-régression Vitest. Détecté uniquement grâce au navigateur réel.
7. **`TestClient`/`httpx` bufferise les réponses SSE infinies** → le flux SSE est testé en pilotant
   directement le générateur ASGI, et vérifié en `curl -N` sur le serveur réel.

### Avertissements restants (non bloquants, documentés)

* **Barres journalières** : l'écart OHLC de la source dépasse la tolérance stricte (cf. critère 4).
  Les valeurs brutes sont conservées et signalées ; aucune correction silencieuse.
* **Calendrier des jours fériés** non implémenté : le statut marché suit le planning hebdomadaire
  24×5 (ouverture dimanche 17:00 ET, clôture vendredi 17:00 ET) et le dit dans son champ `note`.

---

## 8. Comment lancer

```bash
cd smart-market-vision
cp .env.example .env                    # rien à modifier pour démarrer
cd backend && pip install -r requirements.txt
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

* Dashboard : `http://localhost:8000/`
* Swagger : `http://localhost:8000/docs`

Frontend (seulement si le code React est modifié) :

```bash
cd frontend && npm install && npm run build     # regénère dist/, servi par FastAPI
npm run dev                                     # ou hot-reload sur :5173 (proxy /api)
```

### Depuis un téléphone

1. `python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000` (défaut du `.env`).
2. Relever l'IP locale : `hostname -I` (Linux) ou `ipconfig getifaddr en0` (macOS).
3. Ouvrir `http://<IP>:8000/` sur le téléphone (même Wi-Fi). Le WebSocket utilise la même origine.
4. « Ajouter à l'écran d'accueil » pour le rendu plein écran.

Tests : `cd backend && python3 -m pytest tests/ -q` · `cd frontend && npm test` ·
`python3 scripts/verify_live.py http://localhost:8000`.

---

## 9. Réellement fonctionnel aujourd'hui

* Récupération de données Forex **réelles** (10 paires, M5/M15/H1/H4/D1), cache, historique SQLite.
* Détection et affichage de la structure : pivots, HH/HL/LH/LL, tendance BULLISH/BEARISH/RANGE/UNDEFINED.
* Dashboard mobile-first : en-tête LIVE, prix, variation, état de donnée, statut marché,
  sélecteurs de paire et de timeframe, graphique en chandeliers (zoom, déplacement, portrait/paysage).
* Temps réel WebSocket (+ SSE) avec reconnexion et états LIVE / RECONNECTING / DISCONNECTED.
* Scanner de fond qui observe 10 paires, publie les mises à jour et les clôtures de bougies, persiste.
* Contrats prêts pour les phases suivantes : `MarketEvent`, `PatternDetection`, overlay de graphique,
  `TelegramNotifier`, contrat de capture visuelle, table `pattern_detections` (vide).
* Sécurité : aucun secret exposé, aucune capacité d'exécution d'ordre.

## 10. PAS encore implémenté (ne pas attendre de ces éléments)

* **Détecteurs** chartiste, price action, SMC/ICT (BOS, CHoCH, order blocks, FVG, zones de liquidité) —
  l'API et le dashboard affichent `NO ACTIVE DETECTION` et `NOT_IMPLEMENTED`.
* **Génération d'image** du graphique à la détection (`CAPTURE_NOT_IMPLEMENTED` : seul le contrat
  de données existe, aucune image factice n'est produite).
* **Envoi Telegram de détections** : seule l'interface `send_message()` / `send_image()` existe et
  n'est pas branchée sur un flux de détection.
* Calendrier des jours fériés, back-testing, alertes sonores, multi-utilisateur.

**Fin de la Phase 1 — en attente de validation avant toute phase suivante.**
