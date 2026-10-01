# SMART MARKET VISION — RAPPORT FINAL PHASE 4 (moteur SMC / ICT)

Généré le 2026-09-30 (fin de Phase 4). **Aucune Phase 5 n'est commencée : arrêt demandé après ce rapport.**

Périmètre tenu de bout en bout : **scanner / observateur**. Aucun ordre, aucun broker, aucune gestion de
position, aucun BUY / SELL / ENTRY / SL / TP, aucun moteur de confluence global déclencheur, aucun Telegram.
La liquidité est partout présentée comme une **estimation géométrique**, jamais comme une connaissance des
ordres réels.

---

## 1. Tests — par phase et total

| Niveau | Avant Phase 4 | Ajouté en Phase 4 | Total | État |
| --- | --- | --- | --- | --- |
| Backend (pytest) | 401 | **+102** | **503 passed** (17–21 s) | ✅ vert |
| Frontend (vitest) | 29 | **+17** | **46 passed** (2 fichiers) | ✅ vert |
| Navigateur réel — Phase 3 (non-régression) | 42/42 | — | **42/42** | ✅ vert |
| Navigateur réel — Phase 4 | — | **25** | **25/25 PASS / 0 FAIL** | ✅ vert |
| Vérification données réelles (§26) | — | 17 contrôles | **16 PASS / 1 WARN / 0 FAIL** | ✅ vert (WARN assumé) |

Détail des nouveaux tests backend :

| Fichier | Tests | Contenu |
| --- | --- | --- |
| `tests/test_smc_ict_structure.py` | 27 | pivots réutilisés, BOS bull/bear, CHOCH, MSS, définitions uniques |
| `tests/test_smc_ict_detectors.py` | 41 | equal highs/lows, pools, sweeps 3 étapes, FVG + mitigation, OB, breaker, displacement, dealing range, premium/discount |
| `tests/test_smc_ict_engine.py` | 34 | contrat des détections, déduplication, cycle de vie, persistance, temps réel, API, performance, contrôle négatif |

Détail frontend : `src/test/SmcIctPanel.test.tsx` (17 tests) — moteur affiché, regroupement par famille,
élément/sens/statut/prix/barre/critères, mention « estimation » de la liquidité, « pourquoi » (preuves +
critères pondérés), cycle de vie FVG, sélection → graphique, état vide vs erreur, filtre d'historique,
confluence interne (test de régression), aucun mot d'instruction de trading, et le câblage dashboard
(snapshot `SMC_ICT_SNAPSHOT`, événement `SMC_DETECTED` en direct, filtre SMC / ICT, bandeau du graphique).

Aucun test n'a été supprimé, désactivé ou affaibli pour obtenir un PASS : les échecs rencontrés ont été
corrigés à leur cause (section 9).

---

## 2. Détecteurs implémentés (§2 → §16)

Module isolé `backend/app/smc_ict/` — **réutilisation** des briques validées : pivots Phase 2 (`find_swings`),
Event Bus existant, persistance SQLite, système de paramètres, dashboard, coordonnées graphiques. Aucun
second moteur de pivots, aucun second bus, aucun second système de cassure/retest.

| § | Concept | Module | Sortie mesurée |
| --- | --- | --- | --- |
| 2 | Swing high / low | `context.py` (`find_smc_swings`) | `timestamp, index, price, type, strength` (force = nombre de pivots confirmés) |
| 3 | BOS haussier / baissier | `detectors/structure.py` | `structure_before, broken_level, breakout_candle, breakout_price, direction, timestamp` ; cassure = **clôture** au-delà du niveau + buffer ; `BREAK_MODE` publié dans `measurements` (une mèche seule ne casse pas) |
| 4 | CHOCH | `detectors/structure.py` | `previous_structure, broken_swing, new_structure, confirmation_candle` liés aux swings réels |
| 5 | MSS | `detectors/structure.py` | définition unique documentée (décalage après CHOCH avec extension minimale) ; mêmes niveaux publiés que BOS/CHOCH (`BROKEN_SWING`, `BREAK_CLOSE`) |
| 6 | Equal high / low | `detectors/liquidity.py` | `level, touch_count, timestamps, prices, tolerance` ; la bande entière est bornée par la tolérance déclarée (le niveau publié est la moyenne des contacts) |
| 7 | Liquidity pool | `detectors/liquidity.py` | `LIQUIDITY_POOL_ESTIMATE` : inférence géométrique (equal highs/lows, anciens swings), `estimate: true`, ancrage sur un **contact réel** qui contient le niveau |
| 8 | Liquidity sweep | `detectors/liquidity.py` | 3 étapes obligatoires : niveau → mèche au-delà → **réintégration** ; `liquidity_level, sweep_candle, extreme_price, reentry_price, reentry_timestamp` ; pas de sweep sans réintégration |
| 9 | FVG | `detectors/gaps.py` | 3 bougies, `upper_price, lower_price, size, timestamp`, taille minimale configurable, aucun volume inventé |
| 10 | Mitigation FVG | `detectors/gaps.py` | CREATED → ACTIVE → PARTIALLY_FILLED → FILLED (retour = ACTIVE, traversée complète = FILLED), `coverage_share` publié |
| 11 | Order block | `detectors/blocks.py` | dernière bougie opposée → déplacement → BOS/MSS ; `origin_candle, zone_high, zone_low, direction, trigger_event, displacement_measure` |
| 12 | Breaker | `detectors/blocks.py` | jamais détecté indépendamment : cycle ORDER_BLOCK → INVALIDATION → STRUCTURAL_BREAK → BREAKER |
| 13 | Displacement | `detectors/blocks.py` | mesures objectives : range, range/ATR, corps/range, progression, efficacité, progression/ATR |
| 14–15 | Dealing range, premium / discount | `detectors/ranges.py` | range issu de **vrais swings** (`source_high_index/low`, span en ATR), équilibre = milieu, zones premium/discount proportionnelles ; aucun range arbitraire |
| 16 | Confluence interne | `detectors/confluence.py` | **descriptif** : groupes d'objets décrivant le même mouvement ; `trading_signal` gelé à `false` |

Paramètres : `app/smc_ict/params.py` — 17 groupes, préfixe `SMC_ICT_`, `snapshot()` centralisé, exposés et
modifiables via `GET`/`PATCH /api/smc-ict/params` (groupe inconnu ou `trading_signal` ⇒ 400). Aucun
paramètre des phases précédentes n'a été modifié.

---

## 3. Données réelles analysées (§26)

`scripts/verify_smc_ict_live.py` — 10 paires Forex × 3 unités de temps (M15, H1, H4), provider Yahoo réel :

- séries analysées : **30 / 30**
- bougies clôturées analysées : **8 970**
- objets SMC / ICT retenus : **1 325** (30 séries), groupes de confluence : 17
- durée par série : min **79,5 ms** / médiane **134,3 ms** / max **222,6 ms**
- erreurs moteur : **0**, avertissements moteur : **0**
- surface live : API joignable, **400 objets suivis**, `trading_signal: false`

Contrôles anti-fiction (tous PASS) :

| Contrôle | Résultat |
| --- | --- |
| bougies d'ancrage existantes | 0 hors série |
| mesures recomposables sur l'OHLC réel | 0 écart |
| coordonnées à l'intérieur de la bougie | 0 écart |
| confiance recomposée depuis les critères | 0 écart |
| mots d'instruction de trading | 0 |
| volume inventé | 0 (le provider ne fournit pas de volume réel) |
| liquidité marquée comme estimation | 216 pools + 3 sweeps marqués |

**WARN assumé** : 60 avertissements de qualité du provider (gaps de week-end, bougie en cours repliée) sont
conservés et publiés, pas masqués. Ils ne sont pas des avertissements du moteur.

Rapports bruts : `reports/smc_ict_real_data.md` et `reports/smc_ict_real_data.json`.

---

## 4. Répartition des détections (données réelles, 30 séries)

| Élément | Objets | | Statut | Objets |
| --- | --- | --- | --- | --- |
| BEARISH_FVG | 307 | | ACTIVE | 648 |
| BULLISH_FVG | 238 | | FILLED | 396 |
| LIQUIDITY_POOL_ESTIMATE | 216 | | CONFIRMED | 120 |
| EQUAL_HIGH | 127 | | MITIGATED | 82 |
| EQUAL_LOW | 115 | | INVALIDATED | 75 |
| BEARISH_ORDER_BLOCK | 98 | | DETECTED | 4 |
| BULLISH_ORDER_BLOCK | 68 | | **Total** | **1 325** |
| DISPLACEMENT | 39 | | | |
| BOS | 33 | | | |
| BREAKER_BLOCK | 31 | | | |
| DEALING_RANGE | 25 | | | |
| CHOCH | 10 | | | |
| DISCOUNT / PREMIUM | 7 / 4 | | | |
| MSS | 4 | | | |
| LIQUIDITY_SWEEP | 3 | | | |

Lecture honnête : les déséquilibres (FVG) dominent — normal, un FVG se forme plusieurs fois par jour sur 300
bougies — et les balayages de liquidité sont rares (3) parce qu'ils exigent les **trois** étapes
(niveau → mèche → réintégration) sur un marché réellement consommé. Aucun seuil n'a été ajusté pour
« embellir » cette répartition.

Persistance : `pattern_detections` = 679 lignes `SMC_ICT` (679 identifiants uniques, aucune collision),
`market_events` = 2 736 événements SMC (SMC_DETECTED 2 714, SMC_MITIGATED 9, SMC_FILLED 10,
SMC_INVALIDATED 3). Rejouer la même série produit exactement le même nombre de lignes (test dédié).

---

## 5. Contrôle négatif (§25)

Réutilisé tel quel depuis la Phase 3 (fixtures inchangées), sans réglage de seuil :

| Scenario | Objets | Objets / bougie | Structure |
| --- | --- | --- | --- |
| bruit aléatoire (300 bougies) | 43 | 0,1433 | BOS 1, CHOCH 1, MSS 0 |
| marché plat (200 bougies) | 0 | 0,0 | 0 |
| fortement directionnel (200 bougies) | 0 | 0,0 | 0 |

**Faux positifs éventuels, publiés tels quels** : sur du bruit pur, 43 objets apparaissent (≈ 14 pour
100 bougies) — principalement des FVG et des equal levels, par nature statistiques. Le filtre structure
(toutes les phases) applique la règle des 12 bougies et élimine les plus anciens ; ce bruit résiduel est
assumé et **non filtré artificiellement**. Aucune correction de seuil n'a été faite pour atteindre zéro.

---

## 6. Visualisation (§17) et dashboard (§18)

**Graphique** (Lightweight Charts, coordonnées OHLC réelles) :
lignes + libellés pour BOS / CHOCH / MSS (`BROKEN_SWING`, `BREAK_CLOSE`), niveaux de liquidité et pools
(toujours en jaune « estimation »), marqueurs de balayage, **rectangles canvas** pour FVG, order blocks,
breakers et zones premium/discount (primitive `zonePrimitive.ts` : un rectangle par zone réelle, largeur
d'un bar minimum — jamais élargi pour faire joli), dealing range (haut / équilibre / bas).
Limitation de lisibilité conservée : `MAX_OVERLAYS = 3` (les objets au-delà restent sélectionnables dans le
panneau) ; le bandeau indique « 3 / n calques (lisibilité) ».

**Panneau SMC / ICT** (`src/components/SmcIctPanel.tsx`) : 5 blocs — STRUCTURE, LIQUIDITÉ (ESTIMATION),
DÉSÉQUILIBRES (FVG), BLOCS D'ORDRES / BREAKERS, RANGES / PREMIUM·DISCOUNT — et un bloc moteur (état
`ENABLED`, objets suivis, compteurs par statut et par élément, dernier run). Chaque ligne affiche
**élément, sens, statut de cycle de vie, prix mesuré, horodatage de la barre, critères validés (n / n) et
confiance**, avec un badge « ESTIMATION » sur la liquidité et un bouton « POURQUOI » qui déplie les preuves
et les critères pondérés (§19). Historique filtrable par élément. Le panneau distingue explicitement
« aucun objet suivi » d'« API indisponible ».

Captures : `reports/screenshots/phase4_desktop.png` (1440×900, page complète) et
`phase4_desktop_viewport.png` (premier écran), `phase4_mobile_portrait.png` (390×844) et
`phase4_mobile_portrait_viewport.png`, `phase4_mobile_landscape.png` (844×390) et
`phase4_mobile_landscape_viewport.png`.

---

## 7. Temps réel (§23) et état du dashboard

- Même bus que les phases précédentes : `SMC_ICT_SNAPSHOT` livré à la (re)connexion, événements
  `SMC_DETECTED / SMC_CONFIRMED / SMC_MITIGATED / SMC_INVALIDATED / SMC_FILLED / SMC_EXPIRED` diffusés aux
  abonnés (WebSocket + SSE). Aucun second bus.
- Preuve navigateur : snapshot reçu et **rendu sans rechargement** (compteur de navigation intact), ajout
  d'un objet par un événement `SMC_DETECTED` en direct, panneau toujours monté après le flux.
- Non-régression temps réel : le cycle LIVE → RECONNECTING → LIVE de la Phase 3 repasse **42/42**, coupure
  volontaire du backend comprise, avec resynchronisation du panneau en 0,1 s après reconnexion.
- Câblage moteur ↔ API : le scanner exécute le moteur SMC/ICT à chaque tick (≈ 20–38 ms par paire/UT sur
  300 bougies), persiste, publie ; aucune erreur de persistance SMC observée (679 lignes, ids uniques).

---

## 8. Mobile (§28)

Mesuré en navigateur réel, sur le dashboard servi par le serveur :

| Contrôle | Portrait 390×844 | Paysage 844×390 |
| --- | --- | --- |
| débordement horizontal | 0 élément hors cadre (`scrollWidth = 390`) | 0 élément hors cadre (`scrollWidth = 844`) |
| commandes au doigt | 83 commandes, hauteur minimale **32 px** | idem |
| graphique lisible | hauteur **388 px** | hauteur **265 px** |
| panneau SMC / ICT | 39 objets affichés | 39 objets affichés |
| interaction | « POURQUOI » s'ouvre au tap | — |

Les rails qui défilent (paires, tableaux d'historique) restent **internes** à leur conteneur : la page,
elle, ne défile jamais latéralement. Les rectangles et labels ne sont dessinés que s'ils tiennent dans
leur largeur réelle (sinon le label est omis plutôt que tronqué).

---

## 9. Incidents réels rencontrés et corrigés à la racine

Aucun de ces points n'a été contourné par un affaiblissement de contrôle :

1. **Écarts de coordonnées sur données réelles** — les pools étaient dessinés sur la bougie du dernier
   contact, l'équilibre du dealing range sur une barre ne contenant pas ce prix. Corrigé : ancrage du pool
   sur un contact réel contenant le niveau, équilibre dessiné uniquement sur une bougie qui le contient
   (sinon pas de point du tout).
2. **MSS sans niveaux publiés** → `BROKEN_SWING` / `BREAK_CLOSE` ajoutés (même contrat que BOS / CHOCH).
3. **Bande d'egal high/low incohérente avec la tolérance publiée** → la bande entière est désormais bornée
   par la tolérance (spread publié ≤ tolérance publiée), testé.
4. **Confluence SMC affichée avec la forme de la confluence price action** → **bug réel qui cassait tout le
   dashboard** (`Cannot read properties of undefined (reading 'structure')`, écran vide en navigateur). Corrigé
   par un type et un rendu propres aux groupes SMC (direction, familles, éléments), avec test de régression.
5. **Contrôle de retrait de calque faussement négatif** — le test de couleurs confondait le **texte blanc
   anti-aliasé** de l'axe avec du violet clair. Matcher durci (un vrai violet clair est bleuté) plutôt que
   tolérance élargie.
6. **Contrôle « niveaux tracés » dépendant de la palette du motif du moment** — remplacé par une lecture de
   ce que le graphique a réellement créé (compteur d'observabilité `window.__smvChart`), plus le contrôle
   visuel de pixels ; le détail publie désormais les valeurs mesurées.
7. **Étiquette d'axe résiduelle après retrait d'un calque** → demande explicite de repeinture de l'échelle
   de prix lors du retrait des lignes.
8. **Contrôle de moteur obsolète** dans le script Phase 3 (« SMC/ICT non implémenté ») → mis à jour vers le
   contrat Phase 4 (les trois moteurs `ENABLED`), documenté dans ce rapport.
9. **Environnement recyclé en cours de phase** (paquets pip, Chromium et bibliothèques système perdus,
   workspace intact) → procédure de restauration appliquée : `pip install -r backend/requirements.txt`,
   `npm ci`, réinstallation des bibliothèques Chromium, redémarrage propre, `/api/health` vérifié, suite
   **503 tests** relancée **verte**, puis reprise au dernier bloc validé. Aucune phase n'a été reprise de zéro.

---

## 10. Problèmes connus (publiés, non masqués)

1. **Liquidité = estimation** par construction : le moteur ne voit aucun carnet d'ordres. Le vocabulaire
   (`LIQUIDITY_POOL_ESTIMATE`, badge « ESTIMATION », note du panneau) le dit partout.
2. **Bruit résiduel** : 43 objets sur 300 bougies de bruit pur (cf. §5), non filtré artificiellement.
3. **Balayages rares** (3 sur 8 970 bougies) : conséquence des 3 étapes exigées, pas d'un défaut.
4. **Registre plafonné** : le suivi est borné (`max_tracked = 40` par série, registre global élagué à 400
   entrées) pour tenir la charge ; les transitions d'état publiées restent disponibles dans l'historique.
5. **Pré-existant, hors périmètre Phase 4** : le service price action journalise parfois une
   `UNIQUE constraint failed: pattern_detections.id` lors de l'insertion en lot (l'erreur est capturée, le
   moteur continue, aucun impact sur l'affichage). Observé dans les journaux du serveur pendant cette phase ;
   le moteur SMC/ICT n'est pas concerné (déduplication `smc_<sha1>` incluant l'horodatage de la bougie
   source, 679 lignes / 679 identifiants uniques). Non corrigé ici pour ne pas modifier un moteur validé de
   la Phase 3 sans validation.
6. **Avertissements de qualité du provider** (60) conservés et publiés : gaps de week-end et bougie en cours
   repliée. Aucune donnée fictive n'est substituée.

---

## 11. Fichiers créés / modifiés (Phase 4)

**Créés — backend**
`app/smc_ict/{__init__,params,models,measures,context,engine}.py` (43/389/178/146/198/694 lignes),
`app/smc_ict/detectors/{structure,liquidity,gaps,blocks,ranges,confluence}.py` (383/574/275/388/369/87),
`app/services/smc_ict.py` (295), `app/api/smc_ict.py` (281),
`tests/{smc_ict_fixtures,test_smc_ict_structure,test_smc_ict_detectors,test_smc_ict_engine}.py`
(493/277/415/386).

**Créés — scripts / rapports**
`scripts/verify_smc_ict_live.py` (§26), `smv_phase4_browser.py` (validation navigateur §17/§23/§28),
`run_phase3_with_outage.py` (orchestration de la coupure serveur pour la non-régression Phase 3),
`reports/smc_ict_real_data.{md,json}`, `reports/phase4_browser.{md,json}`,
`reports/screenshots/phase4_*.png` (6 captures), ce rapport `PHASE4_REPORT.md`.

**Créés — frontend**
`src/components/SmcIctPanel.tsx` (489), `src/components/zonePrimitive.ts` (118),
`src/test/SmcIctPanel.test.tsx` (592).

**Modifiés — backend**
`app/container.py`, `app/services/scanner.py` (`_run_smc_ict`), `app/api/stream.py`
(`_smc_ict_snapshot` → WebSocket + SSE), `app/main.py`, `app/db/repository.py`
(`history(..., category=…)`), `app/schemas/events.py` (statuts `ACTIVE/MITIGATED/FILLED`, `EventType.SMC_*`,
`SMC_ICT_SNAPSHOT`), `app/services/patterns.py`, `app/services/price_action.py`, `app/api/system.py`
(cartes d'état `ENABLED`), `tests/conftest.py` (fixture `smc_ict`).

**Modifiés — frontend**
`src/App.tsx` (état SMC/ICT, snapshot et événements `SMC_*`, filtre `SMC / ICT`, calques),
`src/components/ChartPanel.tsx` (zones canvas, palette SMC, observabilité, repeinture d'axe),
`src/api/client.ts` (11 appels SMC/ICT), `src/types/market.ts` (contrat SMC/ICT, statuts étendus),
`src/styles/app.css` (badges SMC / estimation, filtre, règles mobiles), `src/test/App.test.tsx`
(mocks SMC/ICT, carte moteur `ENABLED`), `src/test/setup.ts` (stub `attachPrimitive`).

Configuration : aucun changement de `.env` / `.env.example` (les moteurs des phases 1–3 n'y exposent rien) ;
tous les paramètres SMC/ICT restent centralisés dans `app/smc_ict/params.py` et exposés par l'API.

---

## 12. État final

- Backend : `503 passed`, `/api/health` OK, 11 routes SMC/ICT, persistance 679 objets + 2 736 événements.
- Frontend : `46 passed`, build de production servi par l'API, TypeScript sans erreur.
- Navigateur réel : Phase 4 **25/25**, Phase 3 **42/42** (coupure/reconnexion incluse).
- Données réelles : 30 séries Forex, 8 970 bougies, 1 325 objets, 0 erreur, 0 donnée fictive.
- Contrôle négatif exécuté et publié tel quel (bruit 43 / 300 bougies), aucun seuil ajusté.
- Interdits vérifiés : aucun BUY / SELL / ENTRY / SL / TP dans le DOM ni dans l'API, `trading_signal: false`,
  `order_execution: false`, `broker_connection: false`, Telegram `NOT_CONFIGURED`.

**PHASE 4 TERMINÉE — ARRÊT ICI. La Phase 5 n'est pas commencée.**
