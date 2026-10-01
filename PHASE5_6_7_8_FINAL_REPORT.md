# SMART MARKET VISION — RAPPORT FINAL PHASES 5, 6, 7, 8

**Date** : 2026-10-01 · **Version** : `1.0.0-phase8` · **Périmètre** : confluence (P5) → opportunité (P6) → capture (P7) → Telegram (P8) → dashboard P5→P8.
**Statut** : les quatre phases sont livrées, branchées, testées et vérifiées sur données réelles. **Aucune Phase 9 n'est entamée** (consigne finale respectée).

Rappel de cadre, tenu sur l'ensemble du travail : **scanner/observateur uniquement**. Aucun ordre, aucun broker, aucune API d'exécution, aucune gestion de position n'existe dans le code. `BUY` / `SELL` sont des **directions analytiques observées**, jamais des instructions. Aucune donnée fictive n'est produite en production : les fixtures synthétiques ne servent que dans `tests/`.

---

## PHASE 5 — CONFLUENCE

### Livré
| Élément | Fichier |
|---|---|
| Moteur, modèles, paramètres centralisés | `backend/app/confluence/{engine,models,params}.py` |
| Service (fenêtre, dédup, persistance, événements) | `backend/app/services/confluence.py` |
| API (6 routes) | `backend/app/api/confluence.py` |
| Persistance | `confluences` + `confluence_events` (`app/db/models.py`, `repository.py`) |
| Branchement scanner | `_run_confluence()` dans `app/services/scanner.py` |
| Tests | `tests/test_confluence_engine.py` **32** · `tests/test_confluence_pipeline.py` **13** |

### Contrat de normalisation
Chaque détection est normalisée en `{symbol, timeframe, source, type, direction, timestamp, price, status, evidence}`. Les **moteurs P2/P3/P4 n'ont pas été modifiés** : la normalisation se fait à la lecture (`PatternDetection` → dictionnaire commun), avec `reference_price()` (les détections n'ont pas de `.price`), `source_engine.value` et `detected_at_bar_time`.

### Alignement temporel et directionnel
- Fenêtre glissante configurable : `window_bars=6`, `max_age_bars=24`, `validity_bars=30`, `price_band_atr=1.5` × ATR, `min_events=2`, `max_events=12`.
- Un événement plus vieux que `max_age_bars` **n'entre jamais** dans un nouveau groupe (contrôlé par test).
- Alignement directionnel **sans fusion aveugle** : une lecture opposée alimente `contradictions[]` et `against[]`, elle est affichée, et peut faire basculer l'état en `CONTRADICTED`.

### Score 0–10 explicable
Poids centralisés (`/api/confluence/params`, aucun poids caché) :
`STRUCTURE 2 · LIQUIDITY 2 · IMBALANCE 1 · DISPLACEMENT 1 · PRICE_ACTION 1 · CHARTISTE 1 · PREMIUM_DISCOUNT 1 · MULTI_TIMEFRAME 1`.
Chaque point est traçable : `components[]` porte `dimension, label, points, reason, events[], timeframes[]`, doublé de `why[]` (✓) et `against[]` (✗).
**Le score n'est jamais présenté comme une probabilité de gain** — l'interface et l'API le disent explicitement (« score explicable, jamais une probabilité »), et un test frontend interdit le vocabulaire « probabilité de », « chance de », « réussite », « % ».

### États
`NO_CONFLUENCE` (< 3) · `WATCH` (≥ 3) · `CONFLUENCE` (≥ 5) · `STRONG_CONFLUENCE` (≥ 7 **et** ≥ 4 dimensions **et** 0 contradiction) · `CONTRADICTED` (`penalty ≥ 2` avec lecture opposée) · `EXPIRED`.

### Multi-timeframe
Chaque composant expose les TF contributeurs ; les TF contextuels sont les TF plus lents (plafond 2). **Aucune lecture n'est affichée sans son timeframe** (exigence explicite).

### Persistance et déduplication
Identifiant stable `cf_<sha1(symbol|timeframe|direction|window_start)[:16]>` : deux passages du scanner sur la même fenêtre produisent une seule ligne (dédup par `dedup_key`), et l'historique est conservé avec `generation`, `first_seen_at`, `last_seen_at`, `expires_at`.

### Mesures réelles (SQLite de production, 2026-10-01)
```
confluences : CONTRADICTED 13 · NO_CONFLUENCE 14 · WATCH 7 · CONFLUENCE (observées) 2
événements   : CONFLUENCE_DETECTED 71 · CONFLUENCE_CONTRADICTED 73
```

---

## PHASE 6 — OPPORTUNITÉ

### Livré
| Élément | Fichier |
|---|---|
| Moteur, modèles, paramètres | `backend/app/opportunities/{engine,models,params}.py` |
| Service (cycle de vie, anti-spam, outbox) | `backend/app/services/opportunities.py` |
| API (5 routes) | `backend/app/api/opportunities.py` |
| Persistance | table `opportunities` |
| Tests | `tests/test_opportunity_engine.py` **33** · `tests/test_opportunity_pipeline.py` **16** |

### Direction analytique, jamais un ordre
`BUY` / `SELL` / `WATCH` / `NO_TRADE` qualifient une **lecture de marché**. Le payload contient `direction`, jamais d'`entry`, `SL`, `TP`, `size`, `execution`. Le champ `order_execution: false` est renvoyé par l'API, et un test frontend vérifie l'absence de ce vocabulaire dans le panneau.

### Conditions de `BUY` (et symétrique pour `SELL`)
Structure alignée (BOS/CHOCH/MSS) **+** lecture de liquidité (sweep) **+** displacement **+** déséquilibre (FVG / order block) **+** price action de déclenchement **+** confluence suffisante **sans contradiction majeure**.
**Jamais de BUY sur une seule figure** : `required_dimensions=["STRUCTURE"]`, `min_dimensions=4`, `min_score=7`, `min_events=3`, `max_contradictions=0`. Une seule figure bullish ne peut donc pas produire de BUY (contrôlé par test).

### NO_TRADE motivé
`no_trade_reason` est **toujours** renseigné, selon la priorité :
`DISABLED → EXPIRED → STALE_DATA → CONTRADICTORY → LOW_VOLATILITY → MISSING_DIMENSIONS → INSUFFICIENT_CONFLUENCE → STRUCTURE_NON_CONFIRMEE`.
Aucune opportunité n'est inventée pour remplir un quota : sur le marché actuel (calme, séance asiatique/Europe matin), **toutes** les observations enregistrées sont `NO_TRADE` ou `WATCH`, avec leur raison.

### Score séparé
`STRUCTURE 3 · LIQUIDITY 2 · IMBALANCE 1.5 · TRIGGER 1.5 · DISPLACEMENT 1 · CONFLUENCE_LEVEL 1` = 10, exposé en `conditions[]` (`label, passed, detail, points, dimension, gate`). Les critères bloquants (`gate`) sont signalés comme tels. **Ce n'est jamais une « probabilité de réussite ».**

### Cycle de vie et anti-spam
`CREATED → ACTIVE → CONFIRMED → WEAKENED → INVALIDATED → EXPIRED`, `validity_bars=30`, `confirm_bars=3`, `cooldown_seconds=900`, `notify_states=(CREATED, CONFIRMED, INVALIDATED, EXPIRED)`.
Clé stable `op_<sha1(symbol|timeframe|confluence_id)[:16]>` + `alert_key` ; le recouvrement est mesuré sans hindsight (`confirmation_bar_time` vérifié par test).

### Mesures réelles
```
opportunities : 34 lignes · NO_TRADE 32 · WATCH 2 · états ACTIVE 20 / WEAKENED 10 / INVALIDATED 4
événements    : OPPORTUNITY_CREATED 34 · OPPORTUNITY_WEAKENED 10 · OPPORTUNITY_INVALIDATED 4
exemple de direction nommée observée aujourd'hui : USDCAD M15 BUY, op_da9427791f258fb6, 8.0/10, CONFLUENCE 5/10
```
Aucun BUY/SELL n'est fabriqué : les seuls BUY observés sont ceux que les moteurs ont réellement produits pendant la fenêtre de marché active.

---

## PHASE 7 — CAPTURE

### Livré
| Élément | Fichier |
|---|---|
| Paramètres (résolutions, budgets, marges) | `backend/app/capture/params.py` |
| Modèles (scène, priorités, métadonnées) | `backend/app/capture/models.py` |
| Construction de la scène (données réelles) | `backend/app/capture/scene.py` |
| Rendu PNG (Pillow, thèmes, axes, bougies, zones) | `backend/app/capture/renderer.py` |
| Service (file, worker, dédup, persistance) | `backend/app/capture/service.py` |
| API (5 routes) | `backend/app/api/captures.py` |
| Tests | `tests/test_capture_engine.py` **21** |

### Image réelle uniquement
Le PNG est rendu à partir des **chandeliers réellement reçus** (symbole, TF, prix, timestamp, moteurs Chartiste / Price Action / SMC-ICT, zones de confluence). Aucune image de substitution, aucun placeholder, aucune donnée inventée. Si la série est indisponible, **aucune capture n'est produite** (l'API le dit) plutôt qu'une image vide.

### Lisibilité
- Deux résolutions : `phone 1080×1350` (lisible au doigt) et `telegram 1200×675` (aperçu de chat).
- Priorités d'overlays : **1 ÉVÉNEMENT > 2 CONFLUENCE > 3 SOURCE > 4 CONTEXTE**, budgets `context 6 / sources 8 / zones 6 / levels 8 / labels 14`, `label_min_gap 7`.
- Gouttière dédiée `max(230 px, 27 %)`, footer **sous** l'axe des prix, `margin_bottom=108`, allocation de créneaux (`_SlotAllocator`) : **pas d'empilement, pas de chevauchement** (les itérations v1/v2 échouaient précisément là ; la v3 est la version retenue).
- Dé-duplication visuelle des niveaux trop proches (bande 1,2 %) pour éviter les labels empilés.

### Métadonnées et déduplication
`capture_id = cap_<sha1(symbol|timeframe|bar_time|opportunity_id)[:16]>`, avec `opportunity_id, symbol, timeframe, timestamp, bar_time, path, telegram_path, digest sha256, width, height, size_bytes, candles_drawn, overlays{items,dropped}`. Une même barre + même opportunité ⇒ PNG réutilisé (aucun rendu redondant).

### Performance
Rendu fait **hors boucle du scanner** (`asyncio.to_thread` + file de 64). Le scanner ne bloque jamais : il dépose une demande (`_request_capture()`) et continue. Mesures réelles : 12 captures persistées, 29–79 Ko chacune, 0 échec, 0 abandon de file.

### Mesures réelles
```
captures : 12 · toutes en état RENDERED · M15 10 / H1 2 · 1 698 × 1 350 (phone) et 1 200 × 675 (telegram)
événements CAPTURE_READY : 24 (vérifié dans market_events ; l'absence apparente dans bus.history(200)
était une éviction du tampon mémoire, pas une perte : point clos)
```

---

## PHASE 8 — TELEGRAM

### Livré
| Élément | Fichier |
|---|---|
| Paramètres, modes, redaction | `backend/app/telegram/params.py` |
| Messages (structure exacte demandée) | `backend/app/telegram/messages.py` |
| Outbox durable + dispatcher | `backend/app/telegram/outbox.py` |
| API `/status`, `/test` (surchargées en place, clés P1 conservées) | `backend/app/api/system.py` |
| API `/history`, `/params` | `backend/app/api/telegram.py` |
| Persistance | table `telegram_outbox` |
| Tests | `tests/test_telegram_outbox.py` **27** |

### Sécurité du token
`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` viennent **exclusivement** de `.env`. Le token n'est jamais écrit dans le code, jamais journalisé, jamais présent dans une capture, un payload d'API, un événement ou un rapport : `bot_token_preview` renvoie `NOT_SET` ou un aperçu tronqué, et un test de bout en bout vérifie qu'aucun enregistrement ne contient le secret. **Aucune valeur n'a été demandée ni affichée pendant ce travail.**

### Modes
- `NOT_CONFIGURED` : variables absentes ou désactivées ⇒ l'alerte reste `QUEUED`, `attempts=0`, aucune erreur : **le scanner n'est pas pénalisé** et rien n'est perdu.
- `DRY_RUN` (défaut) : l'alerte est marquée `SENT` **sans aucun appel réseau**, avec le message réellement composé et, depuis ce rapport, liée à la **capture réelle** quand elle existe (traçabilité du dashboard).
- `REAL` : uniquement si les deux variables existent **et** `TELEGRAM_MODE=REAL`. `apply_overrides` refuse de changer le mode depuis l'API : il n'y a pas de bascule accidentelle.

### Message structuré (format demandé, extrait réel)
```
🚨 SMART MARKET VISION
USDCAD · M15
🟢 BUY — OPPORTUNITÉ OBSERVÉE
Confluence 5/10
Score : 8/10
État : CREATED
STRUCTURE ✅  IMBALANCE ✅  PRICE ACTION ✅  Volatilite utilisable ✅  DISPLACEMENT ✅   |   LIQUIDITY ✗
Prix : 1.42490
Validité : 2026-10-01 17:30 UTC
Détections : confluence cf_7297e4c819ca19ec : CONFLUENCE 5/10 | Structure haussier (M15) : CHOCH (M15) [+2]
⚠️ Observation uniquement — aucune exécution automatique, aucun ordre.
```
`WATCH` = 👀, `NO_TRADE` sans alerte (`SEND_NO_TRADE=false`), image envoyée après le message ou en légende (`SEND_CAPTURE=true`, `attachment` du PNG telegram).

### Architecture scanner / outbox / dispatcher
`Opportunity → TelegramOutbox → Dispatcher → Telegram API`. Le scanner **dépose** dans l'outbox et repart immédiatement ; le dispatcher tourne dans sa propre tâche (`poll 1,5 s`, `batch 5`). Si Telegram est indisponible : `RETRYING` / `FAILED` avec backoff exponentiel (`5 s ×2`, plafond `min(row.max_attempts, params.max_attempts)`, `max_attempts=5`), le flux marché continue. Statuts : `QUEUED / SENDING / SENT / FAILED / RETRYING / SKIPPED`. Dédup par identité d'alerte `alert_id = al_<sha1(alert_key|event_type)[:16]>` (insert idempotent : une même opportunité ne produit pas deux alertes).

### Mesures réelles
```
telegram_outbox : 3 alertes · toutes SENT en DRY_RUN · tentatives 1/5 · 0 FAILED
événements ALERT_SENT : 3 (trading_signal: false) · ALERT_FAILED : 0
mode courant : NOT_CONFIGURED (aucune variable Telegram dans l'environnement de production)
```

---

## DASHBOARD P5→P8

### Livré
- `frontend/src/components/SignalPanels.tsx` : **MARKET OVERVIEW**, **CONFLUENCE**, **OPPORTUNITÉ**, **ALERTES & TELEGRAM** (statut, file, historique, galerie de captures réelles).
- Panneaux P2/P3/P4 conservés et inchangés (CHARTISTE, PRICE ACTION, SMC / ICT, graphique + overlays).
- `frontend/src/types/market.ts` : contrats P5→P8 (aucun champ inventé, aucun champ optionnel transformé en valeur par défaut).
- `frontend/src/api/client.ts` : `/api/confluence`, `/api/confluence/:id`, `/api/opportunities`, `/api/opportunities/:id`, `/api/captures`, `/api/telegram/status`, `/api/telegram/history`, plus les helpers `captureFileUrl`.
- Temps réel **sans rechargement** : abonnement WebSocket existant, plus `CONFLUENCE_SNAPSHOT` / `CONFLUENCE_*`, `OPPORTUNITY_SNAPSHOT` / `OPPORTUNITY_*`, `CAPTURE_READY`, `ALERT_QUEUED|SENT|FAILED` ; repli REST toutes les 25 s si un événement est manqué (onglet endormi).
- `LIVE ●` et l'horodatage du dernier événement réel sont affichés ; un flux muet passe `RECONNECTING` puis `DISCONNECTED` **au lieu de mentir**.
- Mobile-first : portrait 390×844 et paysage 844×390, **aucun scroll horizontal** (mesuré), cibles tactiles, aucun asset externe.

### Tests frontend
`src/test/App.test.tsx` **29** · `src/test/SmcIctPanel.test.tsx` **17** · `src/test/SignalPanels.test.tsx` **18** = **64 passed**.
Les nouveaux tests vérifient, sur les payloads réels : affichage `5/10` et `8.0/10`, refus explicite du vocabulaire « probabilité de / chance / réussite / % » dans le panneau confluence, « aucun ordre » dans le panneau opportunité, présence obligatoire du motif de NO_TRADE, identité alerte → opportunité → capture, absence de tout token, et `—` (jamais une valeur inventée) quand un champ manque.
La galerie de captures est vérifiée dans les deux sens : les PNG de la paire affichée passent en tête, **ceux des autres paires restent visibles** (chaque vignette porte son symbole) — une capture ne peut donc pas être attribuée à la mauvaise paire, et l'absence de capture sur la paire courante ne vide plus la preuve visuelle de la chaîne.

---

## TESTS ET VÉRIFICATIONS

### Suite backend — **663 passed (25,5 s)**
| Fichier | Tests |
|---|---|
| `test_confluence_engine.py` | 32 |
| `test_confluence_pipeline.py` | 13 |
| `test_opportunity_engine.py` | 33 |
| `test_opportunity_pipeline.py` | 16 |
| `test_capture_engine.py` | 21 |
| `test_telegram_outbox.py` | 27 |
| **sous-total P5→P8** | **142** |
| P1→P4 + API + sécurité + flux (inchangés, toujours verts) | 521 |

`test_api.py::TestCaptureContract` (écrit en P1 pour dire « pas encore implémenté ») a été **renforcé** pour valider la vraie Phase 7 : aucun test supprimé, aucun test affaibli, aucune assertion désactivée.

### Suite frontend — **64 passed**
Build de production `npm run build` OK (`dashboard_build`, servi par le backend sur `/` et `/app`).

### Contrôles navigateur (Chromium 153, données réelles du serveur local)
| Contrôle | Résultat |
|---|---|
| Panneaux présents (overview, confluence, opportunité, alertes) | 13/13 |
| `LIVE` + heure du dernier événement réel | ✅ |
| Desktop 1440×900 / portrait 390×844 / paysage 844×390 | `scrollWidth == clientWidth` partout ⇒ **0 scroll horizontal** |
| Changement de paire (10 paires balayées) | EURUSD → GBPUSD → … ; l'overview suit |
| Changement de timeframe (5 segments) | M15 → H4 effectif |
| Graphique réellement peint | 7 canvas, 4 peints (le 5ᵉ est le panneau de volume) |
| Galerie de captures | **6/6 PNG réels** chargés par le navigateur (toutes paires, paire affichée en tête) |
| Coupure réseau | statut `RECONNECTING`/`DISCONNECTED`, aucun plantage, 17 erreurs réseau absorbées |
| Retour du réseau | retour `LIVE` **et** panneaux ré-alimentés |
| Erreurs console hors coupure | **0** |
| **Problèmes restants** | **aucun** |

### Aperçus du dashboard (fichiers conservés)
`reports/dashboard/` contient les captures d'écran du **dashboard réel** prises sur le serveur local, pour que la preuve visuelle survive à un recyclage de l'environnement :
`dashboard_desktop_complet.png` (page entière, P1→P8) · `dashboard_portrait_390x844.png` · `dashboard_paysage_844x390.png` · `panneau_market_overview.png` · `panneau_confluence.png` · `panneau_opportunite.png` (NO_TRADE motivé : `DIRECTIONS_CONTRADICTOIRES`, conditions manquantes en ✗, contradiction comptée) · `panneau_alertes_telegram.png` (mode, file, 3 alertes `SENT` en DRY_RUN, galerie des captures réelles).
Mesures relevées au moment de ces prises : flux `LIVE`, `CONNECTED`, confluence `0/10`, opportunité `⛔ NO_TRADE`, **aucun scroll horizontal** en 390×844 et 844×390.

### Bout en bout sur données réelles
`backend/tools/live_chain.py` (nouveau, rejouable) exécute : OHLC réels → détections → confluence → opportunité → capture PNG → outbox → dispatch, sur une base temporaire, token jamais affiché.
Résultats du jour :
- **10:16 UTC (marché actif)** : `USDCAD M15 BUY` (`op_da9427791f258fb6`, 8/10) et `USDCHF M15 BUY` (`op_eb777bd02e4aafff`, 7/10) ⇒ 2 captures PNG réelles (`cap_2306d81ce1290e53`, `cap_4cf2638c5d3a7141`), 3 alertes `SENT` en DRY_RUN (2 opportunités + 1 test), file vidée, **0 token** dans les enregistrements, message conforme au format demandé.
- **10:53 UTC (marché calme)** : 25 confluences (aucune au-dessus de 4/10), 25 opportunités **toutes `NO_TRADE`** motivées, **0 capture, 0 alerte** — exactement le comportement attendu : le silence est une conclusion, pas un bug.
- Identité d'événement conservée de bout en bout : `opportunity.alert_key` → `alert_id` → `opportunity_id` → `capture.opportunity_id` (affiché par le script à chaque exécution).

### Contrôle négatif (exigence explicite)
- Marché calme ⇒ aucune direction nommée : `NO_TRADE` avec `STRUCTURE_NON_CONFIRMEE` / `DIRECTIONS_CONTRADICTOIRES` / `INSUFFICIENT_CONFLUENCE`.
- Lectures opposées ⇒ état `CONTRADICTED` affiché avec ses composants négatifs (jamais fusionnés silencieusement).
- Données périmées ⇒ refus `STALE_DATA`, aucune capture, aucune alerte.
- Une seule figure ⇒ jamais un BUY (test dédié).
- Aucun paramètre n'a été ajusté pour obtenir plus de BUY/SELL : les seuils de P5/P6/P7/P8 sont ceux publiés par leurs routes `/params` (relevés dans ce rapport).

### Performance
- Scanner : 13 paires scannées, 0 échec, moteurs en millisecondes (confluence 1,1–3,4 ms, opportunité 0,3–0,4 ms, SMC/ICT 17–87 ms), capture et Telegram **hors** du chemin critique.
- Flux marché maintenu Telegram indisponible : vérifié (mode `NOT_CONFIGURED` en production, le scanner continue et rien n'est perdu — les alertes restent `QUEUED`).

### Résilience au recyclage de l'environnement
Régénération effectuée **deux fois** pendant ce travail (l'environnement a été recyclé à ~10:51 et à ~11:02 UTC ; le second recyclage a fait tomber le preview du dashboard) : `pip install -r backend/requirements.txt` + `python3 -m playwright install chromium-headless-shell` + les 12 bibliothèques système ⇒ **663 tests verts**, contrôles navigateur rejoués, `tools/live_chain.py` rejoué. `RESTAURATION.md` a été mis à jour (§3 : commandes P5→P8, nouveaux compteurs, étape `live_chain.py` ; §5 : commandes Chromium qui échouaient en sortie 127). SQLite intacte (captures et alertes conservées), `/api/health` = `ok`, `/` et `/app` = `200`, reprise au dernier bloc validé sans rien supprimer. Le serveur du dashboard est relancé et sert le build courant.

---

## HORS ARENA — DÉPLOIEMENT ET TELEGRAM

Le dashboard tel qu'affiché dans Arena est servi par la sandbox de la session ; le projet est
autonome (un processus, un port). Tout est documenté dans **`DEPLOIEMENT.md`**, avec les fichiers
`Dockerfile`, `docker-compose.yml`, `start.sh` et l'assistant `backend/tools/telegram_setup.py`.

**Ce que cette vérification a corrigé (vrai bug de packaging)** : `Pillow`, importé par le moteur de
capture de la Phase 7, **n'était pas déclaré** dans `backend/requirements.txt` — il n'existait que
dans l'environnement de développement. Sur une machine neuve, l'application aurait planté à
l'import. Il est désormais déclaré (`Pillow==12.3.0`), et la preuve est faite dans un **venv vierge**
créé pour l'occasion : `663 passed`, puis `./start.sh` → `/api/health` 200 et dashboard 200.

**Telegram** : état actuel confirmé `NOT_CONFIGURED` (`TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID`
vides dans `.env`). La procédure complète (BotFather → `/start` → `chat_id` via
`telegram_setup.py --list-chats` → vérification → `TELEGRAM_MODE=REAL`) est dans `DEPLOIEMENT.md` §5.
L'assistant ne lit le jeton que depuis `.env`, ne l'affiche jamais et nettoie les messages d'erreur :
contrôlé avec un jeton factice (« Unauthorized » affiché, **0 occurrence du jeton** dans la sortie).
Aucune valeur secrète n'a été écrite dans le dépôt.

## GLOBAL

### Ce qui a été tenu, phase par phase
| Exigence | État |
|---|---|
| Ne pas refaire P1→P4, ne pas réécrire l'architecture, ne pas toucher aux seuils des moteurs existants | ✅ (aucun moteur P2/P3/P4 modifié ; seule correction collatérale autorisée : `metadata_json` borné + `_iso_utc`) |
| Aucune donnée fictive en production | ✅ (fixtures uniquement dans `tests/`) |
| Aucun volume inventé, liquidité toujours une estimation explicite | ✅ |
| Aucun ordre / broker / API d'exécution, aucun ENTRY-SL-TP | ✅ (`order_execution: false`, tests dédiés) |
| Tokens : `.env` only, jamais stockés/affichés, redaction, ne pas les demander | ✅ |
| Paramètres centralisés, chaque point du score traçable, aucun poids caché | ✅ (`/params` de chaque phase) |
| Architecture légère, mobile-first, portrait + paysage, 0 scroll horizontal | ✅ |
| Rapport unique puis **STOP, pas de Phase 9** | ✅ (le déploiement hors Arena et la configuration Telegram sont documentés sans toucher à l'architecture) |

### Décisions notables
1. **P5** : normalisation à la lecture plutôt que modification des moteurs (contrainte de non-régression respectée).
2. **P7** : rendu Pillow hors boucle + gouttière dédiée et allocation de créneaux, seules solutions qui garantissent des labels sans chevauchement.
3. **P8** : routes `/telegram/status|test` **surchargées en place** dans `api/system.py` (les tests P1 existants restent valides) ; `/history` et `/params` ajoutés dans `api/telegram.py`.
4. **DRY_RUN** : l'alerte simulée est désormais liée à la **capture réelle** — décision d'observabilité prise pendant ce rapport (avant, `capture_id=None` en DRY_RUN : ce n'était pas un bug, mais c'était une perte d'information pour le dashboard).
5. **`ConfluenceReading`** : le type frontend P5 a été renommé pour ne pas entrer en collision avec la confluence interne de la Phase 3 — le type P3 n'a pas été touché.

### Points ouverts et limites honnêtes
- **Aucune alerte `REAL` n'a été émise** : l'environnement n'a pas de token, et il est interdit d'en fabriquer un. Le chemin REAL est couvert par tests (`send_image` du PNG réel, sinon texte) ; il se validera le jour où l'opérateur met ses variables dans `.env`.
- Les états de marché varient heure par heure : à 10:16 UTC deux BUY réels ont été observés ; à 10:53 UTC, aucun. **Rapporté tel quel, sans ajuster les seuils.**
- `bus.history(200)` (tampon mémoire) ne montre pas toujours les derniers événements ; la référence fiable est la table `market_events` (vérifiée : `CAPTURE_READY` ×24, `ALERT_SENT` ×3).
- La validation navigateur exige une installation locale (Playwright + 12 bibliothèques système) : sans elle, les tests automatisés restent verts mais le contrôle visuel n'est pas rejouable.

### Reproduire
```bash
cd backend && pip install -r requirements.txt && python3 -m pytest tests/ -q      # 663 passed
cd ../frontend && npm ci && npm test -- --run                                     # 64 passed
cd ../backend && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000       # dashboard + API
./start.sh                                            # équivalent en une commande (venv + deps + build)
docker compose up -d --build                          # équivalent en conteneur (données montées dans ./data)
python3 tools/telegram_setup.py                       # état Telegram + marche à suivre (jeton jamais affiché)
python3 tools/live_chain.py --test-alert      # chaîne P5->P8 rejouable, base temporaire, token jamais affiché
```

### Conclusion
Les phases 5 à 8 forment une chaîne complète et cohérente — **analyse → détection → confluence → opportunité → capture → alerte** — explicable de bout en bout, silencieuse quand il n'y a rien à dire, et sans jamais franchir la ligne de l'exécution. **Le développement s'arrête ici : aucune Phase 9 n'est entamée.**
