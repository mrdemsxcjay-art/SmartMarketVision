# PHASE 3 — MOTEUR PRICE ACTION · RAPPORT FINAL

**Projet** : SMART MARKET VISION · scanner/observateur Forex temps réel
**Périmètre** : ajout d'un moteur Price Action déterministe, explicable et traçable
**État** : terminé — en attente de validation utilisateur (aucune Phase 4, aucun SMC/ICT)

---

## 1. Fonctionnalités livrées

| § | Exigence | Livraison |
|---|---|---|
| 2 | 9 détections candlestick | Bullish/Bearish Engulfing, Bullish/Bearish Pin Bar, Hammer, Shooting Star, Inside Bar, Outside Bar, Doji — chacune expose `candle_index, timestamp, open, high, low, close, body_size, upper_wick, lower_wick, range, body_ratio, wick_ratios` |
| 3 | Paramètres centralisés | `app/price_action/params.py` : 12 groupes, tous nommés/documentés/testables, API GET + PATCH comme les paramètres chartistes. Aucun seuil dispersé |
| 4 | Engulfing | Règle quantitative d'englobement du corps réel (`min_coverage`), preuve `{previous_candle, current_candle, coverage_ratio, body_multiple}` |
| 5 | Pin Bar | Définition mathématique complète : corps, mèche dominante, mèche opposée, position du corps, `wick_to_body`, `wick/range` |
| 6 | Hammer / Shooting Star | Règles quantitatives + mouvement préalable mesuré (`required_prior_move_pips`) |
| 7 | Inside Bar | `{mother_candle, inside_candle, range_ratio}` avec `max_range_ratio` configurable |
| 8 | Outside Bar | Expansion de range + `previous_high/low`, `current_high/low` conservés |
| 9 | Doji | `body/range ≤ max_body_ratio` — jamais un test `open == close` |
| 10 | Contexte structurel | IMPULSION (mouvement vs ATR, efficacité), CONSOLIDATION (compression, hauteur de boîte), REJECTION (refus d'un niveau réel), BREAKOUT (réutilise le breakout Phase 2) |
| 11 | FAILED_BREAKOUT | Événement distinct : `breakout_level, breakout_candle, failure_candle, return_price, timestamps, direction` |
| 12 | Retest | Réutilise le RETEST Phase 2 — **aucun second moteur** |
| 13 | Contexte de niveau | `BULLISH_ENGULFING_AT_SUPPORT`, etc. Relations mesurées (`distance_pips`, `age_bars`, `source`) ; jamais un motif isolé présenté comme fort |
| 14 | Confluence | Groupes `{chartist, price_action, structure}`, informatifs, **sans score** (`trading_signal: false`) |
| 15 | Visualisation | Chaque détection trace bougie/marqueur/libellé/niveau/zone depuis l'OHLC réel |
| 16 | Dashboard | Section PRICE ACTION (motif, paire, UT, sens, date, statut, « n / n critères ») + filtres **TOUS / CHARTISTE / PRICE ACTION** |
| 17 | Temps réel | `PRICE_ACTION_DETECTED / CONFIRMED / INVALIDATED / EXPIRED` + `FAILED_BREAKOUT` sur **l'Event Bus existant** (aucun bus parallèle) |
| 18 | Déduplication | Clé stable `sha1(symbol+timeframe+pattern+candle_timestamp)` → même bougie = même `id`, jamais 10 événements |
| 19 | Tests | 116 tests Phase 3 dédiés (fixtures OHLC contrôlées) |
| 20 | Contrôle négatif | Moteur exécuté sur bruit synthétique — résultats bruts ci-dessous |
| 21 | `verify_price_action_live.py` | Run Forex réel + recalcul des mesures + contrôle anti-fiction + contrôle négatif + sonde live |
| 22 | Aucun signal de trading | Uniquement DÉTECTÉ/CONFIRMÉ/INVALIDÉ/EXPIRÉ + faits structurels. Vérifié automatiquement dans l'API **et** dans le DOM |
| 23 | Validation navigateur | 42 contrôles réels (desktop, portrait, paysage, overlays, panneaux, paire, UT, temps réel, reconnexion) |
| 24 | Rapport | ce document |

---

## 2. Fichiers créés / modifiés

### Créés (Phase 3)
```
backend/app/price_action/__init__.py
backend/app/price_action/params.py              paramètres centralisés (12 groupes)
backend/app/price_action/candles.py             métriques OHLC + comparaisons epsilon
backend/app/price_action/models.py              contrat de détection
backend/app/price_action/engine.py              moteur, cycle de vie, confluence, dessin
backend/app/price_action/detectors/candlestick.py   9 figures
backend/app/price_action/detectors/structural.py    impulsion/consolidation/rejet/cassure manquée
backend/app/services/price_action.py            service (bus, persistance, stats)
backend/app/api/price_action.py                 6 routes + PATCH params
backend/tests/price_action_fixtures.py          fixtures OHLC contrôlées
backend/tests/test_price_action_candles.py      44 tests
backend/tests/test_price_action_structure.py    39 tests
backend/tests/test_price_action_pipeline.py     33 tests
scripts/verify_price_action_live.py             §21
frontend/src/components/PriceActionPanel.tsx    §16
frontend/src/test/App.test.tsx                  +13 tests (dont 2 de non-régression)
smv_phase3_browser.py                           §23 (42 contrôles)
PHASE3_REPORT.md, RESTAURATION.md, DIAGNOSTIC_SERVEUR.md
reports/price_action_real_data.{md,json}
```

### Modifiés
```
backend/app/main.py                  version 1.0.0-phase3, routeur price_action
backend/app/api/system.py            PRICE_ACTION_ENGINE = ENABLED (SMC/ICT reste NOT_IMPLEMENTED)
backend/app/api/patterns.py          engines() fusionnés
backend/app/api/stream.py            snapshots PRICE_ACTION sur WS + SSE
backend/app/schemas/events.py        PRICE_ACTION_* + FAILED_BREAKOUT
backend/app/container.py             Service Price Action injecté
backend/app/services/scanner.py      _run_price_action à chaque tick
frontend/src/App.tsx                 état PA, filtre, calendriers, temps réel
frontend/src/components/ChartPanel.tsx  overlays multi-détections, lisibilité
frontend/src/hooks/useMarketStream.ts   correction du socket fantôme (voir §7)
frontend/src/types/market.ts, src/api/client.ts, src/styles/app.css
README.md, .env.example
```

**Fondations Phase 1 / Phase 2 : aucune réécriture, aucun moteur remplacé, aucun second bus, aucun second système de breakout/retest.**

---

## 3. Tests

### Backend — `pytest tests/ -q`

| Bloc | Tests | Résultat |
|---|---|---|
| Phase 1 | 146 | ✅ 146 passed |
| Phase 2 | 139 | ✅ 139 passed |
| **Phase 3** | **116** | ✅ **116 passed** |
| **Total** | **401** | ✅ **401 passed in 12,90 s** |

Détail Phase 3 : `test_price_action_candles.py` 44 · `test_price_action_structure.py` 39 · `test_price_action_pipeline.py` 33
(API, coordonnées sur bougies réelles, WebSocket/SSE, persistance, paramètres PATCH 400/422, scanner, confluence).

### Frontend — `npx vitest run` / `npx tsc --noEmit`

| Contrôle | Résultat |
|---|---|
| Tests | ✅ **29 passed** (16 hérités Phase 2 + 13 Phase 3) |
| TypeScript | ✅ **0 erreur** |

Les 13 nouveaux tests couvrent : panneau PA, état vide explicite, filtres, overlay + masquage, preuves/critères,
états de marché, absence de recommandation, événement temps réel, snapshot, cycle CONFIRMÉ → INVALIDÉ,
confluence, et **2 tests de non-régression** du socket fantôme (ils échouent sur l'ancien code, passent sur le nouveau).

### Navigateur réel — `smv_phase3_browser.py`

**42 / 42 PASS** (Chromium headless, serveur live, données réelles) :

- desktop 1440×900 : panneau, critères, contexte, historique, confluence ;
- snapshot d'état livré à la connexion et identique à l'API (7 = 7) ;
- overlay : 9 420 pixels price action + 5 583 pixels de niveau réellement peints ;
- filtres : le calque PA **disparaît** en vue chartiste (0 pixel) et revient en TOUS ;
- changement de paire : UI = API (7 = 7) en 0,2 s, **0 ligne résiduelle** de la paire précédente ;
- changement d'UT : UI = API (0 = 0, état vide cohérent) ;
- portrait 390×844 : boutons de filtre ≥ 40 px, boutons d'action ≥ 32 px, **aucun débordement horizontal (0 px)**, aucun libellé tronqué ;
- paysage 844×390 : graphique entièrement visible (786 × 265 px) ;
- temps réel : LIVE → RECONNEXION forcée → LIVE, **sans rechargement** (tag de fenêtre conservé), snapshot re-livré ;
- aucune instruction de trading dans le DOM, aucune erreur console hors coupure volontaire.

---

## 4. Vérification sur données Forex réelles (§21)

`python3 scripts/verify_price_action_live.py --timeframes M5,M15,H1,H4 --limit 300`

| Mesure | Valeur |
|---|---|
| Séries analysées | **40 / 40** (10 paires × 4 UT) |
| Provider / état | `yahoo` · `CONNECTED` (aucune donnée synthétique) |
| **Bougies réelles analysées** | **11 960** bougies clôturées |
| **Détections Price Action** | **280** (2,34 % des bougies) |
| Erreurs d'analyse | **0** |
| Résultat | **16 PASS / 1 WARN / 0 FAIL** |

### Répartition par motif

| Motif | Nb | Motif | Nb |
|---|---:|---|---:|
| INSIDE_BAR | 58 | BULLISH_PIN_BAR | 24 |
| DOJI | 38 | BULLISH_ENGULFING | 18 |
| OUTSIDE_BAR | 37 | BEARISH_PIN_BAR | 15 |
| FAILED_BREAKOUT | 36 | HAMMER | 14 |
| BEARISH_ENGULFING | 30 | REJECTION | 5 |
| | | SHOOTING_STAR | 4 |
| | | IMPULSION | 1 |

Statuts : CONFIRMED 161 · DETECTED 87 · EXPIRED 20 · INVALIDATED 12.

### Répartition par paire

AUDUSD 25 · EURGBP 25 · EURJPY 31 · EURUSD 25 · GBPJPY 25 · GBPUSD 30 · NZDUSD 22 · USDCAD 35 · USDCHF 27 · USDJPY 35

### Répartition par unité de temps

M5 57 · M15 58 · H1 77 · **H4 88**

### Contrôle anti-fiction (tous PASS)

0 détection orpheline · 0 incohérence de mesure recalculée depuis l'OHLC · 0 coordonnée hors bougie réelle ·
0 écart de `confidence` vs critères pondérés · volume `null` partout (jamais inventé) · aucune instruction de trading.

### Warnings (honnêtes, non bloquants)

La sonde d'instance live a été **corrigée** (elle ne considérait que les détections `DETECTED`, ce qui la faisait
échouer à tort) → elle compte désormais toutes les détections suivies, tous statuts confondus.
9 types de warning d'ingestion, tous explicites : bougie en cours repliée dans la bougie courante, bougie en
cours re-datée sur le début de sa période, bougies sources incomplètes (week-ends/jours fériés). Aucun
warning ne concerne le moteur Price Action lui-même.

---

## 5. Contrôle négatif (§20)

Série de bruit synthétique, 300 bougies, sans structure :

| Mesure | Résultat |
|---|---|
| Détections totales | **5** (1,67 % des bougies) — WARN car > 1 % |
| Répartition | BULLISH_ENGULFING 2 · INSIDE_BAR 2 · OUTSIDE_BAR 1 |
| Structure inventée | **aucune** (0 impulsion, 0 consolidation) |

**Le moteur ne produit pas massivement de figures sur une série sans structure.** Les 5 détections sont des
figures de géométrie locale (englobement, imbrication, expansion de range) qui existent mathématiquement dans
le bruit. **Aucun seuil n'a été modifié pour faire baisser ce nombre** : le résultat est publié tel quel.

---

## 6. Faux positifs observés

- **Sur bruit synthétique** : 5 détections / 300 bougies (voir §5) — difficulté structurelle du bruit, non corrigée artificiellement.
- **Sur données réelles** : les figures les plus fréquentes sont **INSIDE_BAR (58)** et **DOJI (38)**, deux figures « faibles » par nature ; elles sont correctes géométriquement mais peu informatives isolément — c'est précisément pourquoi le contexte de niveau (§13) et la confluence (§14) existent, et pourquoi aucun score final n'est produit.
- **IMPULSION 1 seule sur 40 séries** : la règle est volontairement stricte (mouvement ≥ 1,5 ATR **et** ≥ 15 pips, efficacité ≥ 0,8). Sous-détection assumée plutôt que sur-détection.
- Aucun faux positif n'a été observé sur les mesures elles-mêmes : les 0 incohérences du contrôle anti-fiction montrent que chaque chiffre affiché est recalculable depuis l'OHLC.

---

## 7. Problèmes corrigés pendant la validation navigateur (causes réelles)

| # | Problème constaté | Cause réelle | Correctif |
|---|---|---|---|
| 1 | Panneau PA figé sur l'ancienne paire après changement de paire/UT | `useMarketStream` : les handlers `onclose` d'une souscription **périmée** planifiaient une reconnexion → un **socket fantôme** rouvrait l'ancienne paire ~1 s plus tard et écrasait le panneau avec son snapshot | Chaque souscription possède son socket et une garde de génération ; les callbacks tardifs sont ignorés. **+2 tests de non-régression** (échouent sur l'ancien code) |
| 2 | Débordement horizontal de **129 px** sur mobile (390 px) | `.grid-2` et `.card` en `min-width: auto` : le tableau d'historique chartiste (min-content 481 px) empêchait la colonne de rétrécir | `grid-template-columns: minmax(0, 1fr)` + `min-width: 0` (mobile et desktop à 2 colonnes) |
| 3 | Graphique illisible : ~30 lignes de niveaux empilées, libellés superposés | 6 calques × 4 niveaux dont 2 doublons, tous étiquetés | 3 calques max, déduplication par prix, **seule la détection de référence porte les libellés** ; le bandeau annonce « 3 / 6 calques » |

Deux contrôles du script §23 étaient mal ciblés et ont été **corrigés, pas désactivés** : le compteur de filtres
(un `<span>` de 14 px) était mesuré au lieu des 3 boutons (40 px), et la preuve d'overlay comparait le nombre de
pixels opaques d'un canvas toujours plein — remplacée par une double preuve de couleur (positive et négative).

---

## 8. État mobile et temps réel

**Mobile** : utilisable au doigt. Portrait 390×844 et paysage 844×390 validés, aucun scroll horizontal
(0 px en 390 et en 320), boutons de filtre 40 px, boutons d'action ≥ 32 px, aucun libellé tronqué,
graphique entièrement accessible en paysage, tableaux d'historique à défilement interne.

**Temps réel** : WebSocket unique, reconnexion automatique avec back-off, statut LIVE/RECONNEXION honnête
(« socket ouvert » ≠ « données reçues »), snapshots d'état à la (re)connexion sur le **même** Event Bus.
Test réel effectué en coupant le serveur : `LIVE → RECONNECTING → LIVE`, sans rechargement de page.

---

## 9. Limites et problèmes connus

1. **`flat_noise`** : 1,67 % de détections sur bruit pur (WARN). Non masqué, non « optimisé ».
2. **Figures faibles fréquentes** : INSIDE_BAR et DOJI dominent le volume. Le contexte est fourni, mais aucune hiérarchie de « qualité » n'est produite (interdit §14 : pas de score).
3. **IMPULSION rare** (1/40 séries) : règle stricte, sous-détection volontaire.
4. **Cycle de vie INVALIDÉ** : le pipeline couvre CONFIRMED et EXPIRED ; l'INVALIDATED est produit par le moteur mais sa sémantique de bascule (quand une détection déjà invalidée doit rester dans la liste suivie) mérite une décision produit — à trancher avant toute modification du moteur.
5. **Libellés serrés** : quand plusieurs niveaux sont à quelques pips, les étiquettes de l'axe peuvent se chevaucher (cosmétique).
6. **Paramètres PATCH en mémoire** : les modifications via `/api/price-action/params` ne sont pas persistées entre redémarrages (choix assumé, aligné sur les paramètres chartistes).
7. **Volume** : jamais utilisé comme critère, il n'est pas fourni par le provider (affiché `null`).
8. **Fenêtre d'analyse** : 300 bougies (limite de la fenêtre API) — au-delà, historique non analysé.
9. **RECONNEXION sur serveur froid** : le snapshot n'est émis que s'il existe un état à transmettre ; après un redémarrage à froid, la resynchronisation se fait par les événements live + le poll REST 30 s (comportement documenté, pas un bug).

---

## 10. Garanties respectées

- Aucun ordre, aucun broker, aucune position, aucune exécution automatique.
- Aucun BUY/SELL/ENTRY/SL/TP — vérifié automatiquement dans l'API et dans le DOM.
- Aucun SMC/ICT (Order Blocks, FVG, BOS, CHoCH, Liquidity Sweep) : `SMC_ICT_ENGINE = NOT_IMPLEMENTED`.
- Aucun Telegram de trading (`TELEGRAM = NOT_CONFIGURED`, jetons vides, jamais affichés).
- Aucune donnée synthétique en production ; fixtures synthétiques **réservées aux tests**.
- Aucun test modifié pour masquer un échec ; aucun test supprimé.
- Phase 1 et Phase 2 intactes, aucun moteur remplacé, aucun second Event Bus.

---

## 11. Où regarder

| Élément | Chemin |
|---|---|
| Rapport données réelles | `reports/price_action_real_data.md` (+ `.json`) |
| Captures navigateur | `smv-phase3-desktop.png`, `-portrait.png`, `-landscape.png`, `-overlay-desktop.png` |
| Script navigateur §23 | `smv_phase3_browser.py` |
| Script données réelles §21 | `scripts/verify_price_action_live.py` |
| Procédure de restauration | `RESTAURATION.md` |
| Diagnostic serveur | `DIAGNOSTIC_SERVEUR.md` |

---

**FIN DE LA PHASE 3 — arrêt demandé.** Aucune Phase 4, aucun SMC/ICT, aucun Telegram de trading,
aucun BUY/SELL/ENTRY/SL/TP. En attente de validation.
