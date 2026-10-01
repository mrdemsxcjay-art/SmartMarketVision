# SMART MARKET VISION — PHASE 2 REPORT (moteur de détection chartiste)

**Date** : 2026-09-30 · **Version** : `1.0.0-phase2` · **Statut** : terminé, en attente de validation utilisateur
**Règle absolue tenue** : aucune figure n'est « détectée » parce qu'elle y ressemble — chaque détection est
reproductible depuis les OHLC réels + les paramètres, et le dit.

---

## 1. Ce qui a été livré

Un **moteur chartiste déterministe** branché sur les données Forex réelles, avec persistance du cycle de vie,
diffusion temps réel et rendu graphique :

```
bougies réelles (Yahoo)  →  scanner  →  ChartPatternEngine
                                            ├─ pivots (extrêmes confirmés)
                                            ├─ 10 détecteurs (chartiste uniquement)
                                            ├─ dédup (une identité par formation)
                                            └─ cycle de vie DETECTED → BREAKOUT → CONFIRMED / INVALIDATED / EXPIRED / RETEST
                                                     │
                          Event Bus ── WebSocket / SSE ─┤
                          SQLite (pattern_detections) ──┤
                          API /api/detections…  ────────┘  →  dashboard : panneau + tracé sur le graphique
```

Aucun ordre, aucun broker, aucune position : l'application **observe**.

---

## 2. Fichiers créés / modifiés

### Créés (backend)

| fichier | rôle |
|---|---|
| `backend/app/patterns/params.py` | **tous** les seuils, centralisés (`PatternParams`, env `PATTERN_*`), exposés/validés par l'API |
| `backend/app/patterns/models.py` | `Pivot`, `BarContext`, `Candidate`, `Line`, `size_atr` (échelle de volatilité) |
| `backend/app/patterns/pivots.py` | détection des pivots (`find_pivots`, `alternate`), ATR (court + long), `size_threshold` |
| `backend/app/patterns/geometry.py` | ajustement de droites (LSQ), largeur, apex, pente médiane, touches |
| `backend/app/patterns/confidence.py` | `confidence = 100 × Σ(poids validés) / Σ(poids)` — jamais arbitraire |
| `backend/app/patterns/drawing.py` | construction du dessin (niveaux, droites, zones, marqueurs) + coordonnées |
| `backend/app/patterns/detectors/reversals.py` | Double Top / Double Bottom, Épaules-Tête-Épaules et inversée |
| `backend/app/patterns/detectors/triangles.py` | Triangles ascendant / descendant / symétrique, biseaux, canaux |
| `backend/app/patterns/detectors/consolidations.py` | Rectangle, Support / Résistance (clusters de pivots) |
| `backend/app/patterns/detectors/flags.py` | Drapeaux et fanions haussiers / baissiers |
| `backend/app/patterns/engine.py` | orchestration, dédup `ct_<sha1>`, cycle de vie, événements, anti-flood |
| `backend/app/services/patterns.py` | `PatternService` : analyse → commit → événements → persistance |
| `backend/app/api/patterns.py` | `/api/detections`, `/active`, `/history`, `/{id}`, `GET|PATCH /api/patterns/params` |
| `backend/tests/pattern_fixtures.py` | générateur de séries synthétiques **réservé aux tests** |
| `backend/tests/test_patterns_{reversals,trendlines,consolidation,lifecycle,pipeline,pivots,scenarios}.py` | suite Phase 2 (139 tests) |
| `frontend/src/components/PatternsPanel.tsx` | panneau DÉTECTIONS CHARTISTES + MOTIFS ACTIFS + HISTORIQUE |
| `scripts/verify_patterns.py` | run sur données réelles + rapport markdown/JSON |
| `scripts/verify_phase2_live.py` | 27 vérifications Phase 2 sur l'instance qui tourne |
| `reports/patterns_real_data.{md,json}` | rapport du run réel (40 séries, 11 960 bougies) |
| `/home/user/smv_phase2_*.png` | captures navigateur réel (portrait, tracé, paysage, temps réel) |

### Modifiés

| fichier | modification |
|---|---|
| `backend/app/schemas/events.py` | contrat Phase 2 : 13 `EventType`, `PatternDetection` complet, `DetectionsResponse.stats` |
| `backend/app/db/models.py` | `PatternDetectionRow` : cycle de vie + JSON (evidence, drawing, paramètres, breakout, retest, watch_levels) |
| `backend/app/db/repository.py` | `DetectionRepository` : upsert par id, historique filtrable, `evidence_points`/`watch_levels` exposés |
| `backend/app/db/base.py` | migration **additive** (15 colonnes ajoutées sans perdre une ligne Phase 1) |
| `backend/app/services/scanner.py` | `_run_patterns()` : une analyse par bougie clôturée nouvelle |
| `backend/app/container.py` | `Container.patterns` |
| `backend/app/api/system.py` | bloc `patterns` réel + statut des moteurs (chartiste ENABLED) |
| `backend/app/api/stream.py` | `DETECTIONS_SNAPSHOT` envoyé à **une** connexion (pas de broadcast) |
| `backend/app/main.py` | inclusion du routeur patterns, version/phase, capacités |
| `backend/app/providers/yahoo.py` | réalignement de la bougie **en cours** sur son début de période (prix inchangés) |
| `frontend/src/App.tsx` | sélection d'une détection, évènements chartistes, snapshot de reconnexion |
| `frontend/src/components/ChartPanel.tsx` | tracé réel (niveaux, droites, contacts, bandeau) |
| `frontend/src/api/client.ts`, `types/market.ts`, `styles/app.css` | endpoints + types + styles Phase 2 |
| `frontend/src/test/App.test.tsx` | 6 tests Phase 2 (panneau, historique, tracé, temps réel, confirmation) |
| `scripts/verify_live.py` | critères Phase 1 mis à jour (le stub « aucune détection » devient « aucune détection fictive ») |
| `frontend/vite.config.ts`, `README.md`, `.gitignore` | build dans `dashboard_build/` (conservé, servi par FastAPI) |

Phase 1 n'a été touchée que là où Phase 2 l'exigeait (contrat de statut, stub de détection, provider) : logs,
cache, structure, sécurité, Telegram, capture, mobile-first restent tels quels.

---

## 3. Motifs implémentés

| famille | motifs | moteur |
|---|---|---|
| Retournements | Double Top, Double Bottom, Épaules-Tête-Épaules, ETE inversée | `reversals.py` |
| Triangles | ascendant, descendant, symétrique | `triangles.py` |
| Biseaux | ascendant (bearish), descendant (bullish) | `triangles.py` |
| Consolidation | Rectangle | `consolidations.py` |
| Continuation | Drapeau haussier / baissier, Fanion haussier / baissier | `flags.py` |
| Niveaux | Support, Résistance, Canal | `consolidations.py`, `triangles.py` |
| Événements | Breakout, Retest | `engine.py` (états séparés, jamais fusionnés) |

**Non implémentés (interdits en Phase 2, interfaces seulement)** : Price Action avancé, SMC/ICT, Order Blocks,
FVG, BOS, CHoCH, Liquidity Sweep, Telegram réel, exécution d'ordres. `/api/status` les déclare
`NOT_IMPLEMENTED` et aucun événement ne peut en provenir.

### Conditions mesurables (extrait des critères rendus visibles dans l'UI)

* **Double Top/Bottom** : 2 extrêmes de même type, séparation 5–120 bougies, écart ≤ 5 pips **et** ≤ 0,5 ATR,
  creux/sommet intermédiaire ≥ 8 pips **et** ≥ 1 ATR **et** ≥ 20 % de la jambe précédente, aucun pivot
  intermédiaire au-delà de la paire, formation récente (≤ 60 bougies), neckline = réaction.
* **ETE / ETE inversée** : 5 pivots alternés, tête ≥ 6 pips/0,6 ATR au-dessus (ou dessous) des deux épaules,
  épaules à ±8 pips, vallées ≥ 8 pips, neckline de pente ≤ 0,25 ATR/bougie, **contexte de tendance obligatoire**
  (≥ 25 pips / 2 ATR sur 40 bougies).
* **Triangles** : ≥ 3 touches **par** ligne (jamais 2), ≥ 5 touches au total, tolérance 5 pips/0,5 ATR,
  convergence mesurée (contraction ≥ 30 %), apex non dépassé, largeur minimale 25 pips/1,5 ATR.
* **Biseaux** : ≥ 3 touches par ligne, ≥ 6 au total, les deux pentes dans le même sens **et** convergentes,
  contraction ≥ 25 %.
* **Rectangle** : support et résistance horizontaux (dérive ≤ 0,5), ≥ 2 touches par côté, hauteur ≥ 15 pips,
  boîte = zone traçable.
* **Drapeaux / fanions** : impulsion préalable ≥ 2,0 ATR/25 pips sur ≤ 30 bougies et ≥ 55 % de bougies alignées,
  consolidation de 5 à 60 bougies, largeur ≤ 2,0 ATR (ATR **locale du pôle**) et ≤ 50 % du pôle, dérive ≤ 0,5,
  retracement ≤ 60 % ; fanion = contraction mesurée ≥ 20 %.
* **Support/Résistance** : clusters de pivots (tolérance 6 pips/0,5 ATR), ≥ 2 touches, réaction ≥ 0,5 ATR,
  niveau non dépassé durablement, ≤ 60 bougies depuis la dernière touche, force = touches + réaction + récence.
* **Canal** : deux droites quasi parallèles (écart de pente relatif ≤ 0,35), ≥ 3 touches par ligne,
  dérive de largeur ≤ 0,5, largeur ≥ 25 pips/1,5 ATR.
* **Breakout** : clôture **au-delà** du niveau + marge de 1 pip, bougie confirmante identifiée, ≤ 80 bougies
  après la formation ; **jamais** de volume inventé (le flux FX renvoie 0 → `null`).
* **Retest** : uniquement **après** une cassure confirmée, tolérance 3 pips, ≤ 30 bougies après la cassure.
* **Anti sur-détection global** : fenêtre 300 bougies, ≥ 60 bougies closes, 2 pivots confirmés
  (`pivot_left/right = 2`), bougies clôturées uniquement, maximum 2 détections par motif et par série.

---

## 4. Architecture du moteur

* **Pivots** : `{index, time, price, type: HIGH|LOW, confirmed_at_index}` — un pivot n'existe que confirmé par
  les bougies suivantes ; `alternate()` garantit l'alternance haut/bas.
* **Deux ATR** : l'ATR court (14) mesure la volatilité *du moment* (seuils de pente) ; l'ATR long (100) est
  l'échelle de taille (`size_atr`) — sans lui, un ATR qui s'écrase dans une consolidation silencieuse
  rendrait toute figure impossible.
* **Dédup** : `ct_<sha1(symbol|timeframe|motif|signature des pivots)[:16]>` — **une seule identité** pour toute
  la vie de la formation ; aucun renvoi tant que la formation n'a pas changé.
* **Cycle de vie séparé** : `PATTERN_DETECTED` / `BREAKOUT_DETECTED` / `PATTERN_CONFIRMED` /
  `PATTERN_INVALIDATED` / `PATTERN_EXPIRED` / `RETEST_DETECTED`. Une cassure haussière d'une figure baissière
  est une **invalidation**, jamais une confirmation (`_breakout_levels()` filtre par sens).
* **Suivi des formations vivantes** : `_refresh_tracked()` réévalue la cassure/invalidation/expiration même
  quand les pivots sont sortis de la fenêtre des détecteurs (sans lui, une formation détectée ne serait jamais
  confirmée après 60 bougies).
* **Performance** : moteur pur, une passe ≈ **40–60 ms** par série de 300 bougies ; analyse uniquement sur
  bougie nouvellement clôturée (pas de recalcul à chaque tick) ; 40 séries analysées en 2,4 s dans le run réel.
* **Explainability** : chaque détection porte `evidence[]` (phrases avec prix/écarts en pips), `evidence_points`
  (pivots nommés, mesures), `confidence_factors[]` (critère + poids + valeur), `parameters{}` réellement utilisés.

---

## 5. Tests

| suite | nombre | résultat |
|---|---|---|
| **Phase 1 (backend)** | **146** | ✅ tous verts |
| **Phase 2 (backend)** | **139** | ✅ tous verts |
| **Total backend** | **285** | ✅ `285 passed in 12.38s` |
| **Frontend (vitest)** | **16** (10 Phase 1 + 6 Phase 2) | ✅ tous verts |

Répartition Phase 2 : scénarios de référence 37 · pipeline API/temps réel/persistance/scanner 28 ·
consolidation 19 · retournements 17 · triangles/biseaux/canaux 16 · cycle de vie et dédup 14 · pivots/ATR/params 8.

Ce qui est réellement testé : détection positive par motif, **négatifs** (deux points par ligne, épaules trop
différentes, profondeur insuffisante, tolérances dépassées, figure divergente, consolidation sans pôle…),
bornes (séparation min/max, fenêtre, nombre de bougies), tolérance, confirmation (clôture exigée, mèche refusée),
invalidation, expiration, retest (impossible sans cassure), dédup (même id, pas de ré-émission, id stable après
cassure), coordonnées traçables, confiance recalculée, persistance (une ligne par formation, réouverture du
dépôt), API, WebSocket **et** SSE, absence de détection fictive, non-analyse des bougies ouvertes.

**Aucun test n'a été modifié pour obtenir un résultat positif et aucun test en échec n'a été supprimé.**
Deux tests Phase 1 dépendaient de l'heure d'exécution (bougie « future » à +2 h et barre partielle à
-5 min) : ils ont été rendus indépendants de l'horloge, et deux tests ajoutés pour le réalignement de la
bougie en cours côté provider.

---

## 6. Validation live (instance réelle)

| vérification | résultat |
|---|---|
| `scripts/verify_live.py` (Phase 1 sur données réelles) | **44/46 PASS**, 2 WARN documentés (artefact OHLC de ~3 % des bougies D1 chez la source, conservé tel quel) |
| `scripts/verify_phase2_live.py` (Phase 2) | **27 PASS / 0 WARN / 0 FAIL** |
| Navigateur réel — portrait 390×844, paysage 844×390 | **16/16 PASS** |
| Navigateur réel — reconnexion + données poussées | **9/9 PASS** (coupure détectée → LIVE, `DETECTIONS_SNAPSHOT` reçu, liste à jour, aucun rechargement) |

Vérifications Phase 2 les plus fortes :

* **chaque point tracé tombe dans une bougie réelle** : les coordonnées des détections sont recroisées avec les
  bougies servies par l'API (`low ≤ prix ≤ high`) — 36 points contrôlés, 0 écart ;
* **confiance recalculée** : `confidence == 100 × Σ(poids validés)/Σ(poids)` pour toutes les détections (0 écart) ;
* **aucun volume inventé** : `volume` `null` partout sur un flux qui ne fournit pas de volume réel ;
* **moteurs interdits** : `PRICE_ACTION_ENGINE` et `SMC_ICT_ENGINE` = `NOT_IMPLEMENTED`, et aucune détection ne
  provient d'un autre moteur que `CHART_PATTERN_ENGINE` ;
* **sécurité** : `order_execution=false`, `broker_connection=false`, `position_management=false`.

### Temps réel (scénario rejoué)

Dashboard ouvert → backend **redémarré** pendant la session → le client passe RECONNECTING puis LIVE tout seul,
reçoit `DETECTIONS_SNAPSHOT` (état chartiste courant) puis les événements suivants, **sans rechargement de page**
(le marqueur de fenêtre est intact, le compteur de navigations reste à 1).

---

## 7. Run sur données réelles (résultat brut, à relire par un humain)

`cd backend && python3 ../scripts/verify_patterns.py --timeframes M15,H1,H4,D1`
→ 40 séries (10 paires × 4 UT), **11 960 bougies réelles analysées**, **219 détections**, **0 erreur moteur**.
Rapport complet : `reports/patterns_real_data.md` (+ données brutes `reports/patterns_real_data.json`).

| motif | total | DETECTED | CONFIRMED | INVALIDATED | EXPIRED |
|---|---|---|---|---|---|
| RESISTANCE | 61 | 61 | 0 | 0 | 0 |
| DOUBLE_BOTTOM | 50 | 6 | 22 | 22 | 0 |
| SUPPORT | 41 | 41 | 0 | 0 | 0 |
| DOUBLE_TOP | 37 | 5 | 23 | 9 | 0 |
| HEAD_SHOULDERS | 9 | 1 | 7 | 1 | 0 |
| RECTANGLE | 8 | 7 | 1 | 0 | 0 |
| INVERSE_HEAD_SHOULDERS | 7 | 3 | 3 | 1 | 0 |
| CHANNEL | 2 | 0 | 2 | 0 | 0 |
| FALLING_WEDGE | 2 | 1 | 1 | 0 | 0 |
| SYMMETRICAL_TRIANGLE | 1 | 1 | 0 | 0 | 0 |
| RISING_WEDGE | 1 | 0 | 1 | 0 | 0 |

Par unité de temps : H1 62 · M15 57 · H4 54 · D1 46. Temps d'analyse : min 38,5 ms / médiane 44,7 ms / max 122,8 ms par série.

**Ce que ce run ne prouve pas** : que ces figures sont « correctes » au sens chartiste, ni rentables. Chaque cas
est livré avec ses mesures (écart en pips vs tolérance, profondeur, séparation, pente, contraction…) pour être
validé ou rejeté par un humain. Les biais observés sont cohérents avec ce qu'on attend d'un moteur de ce type :

* les **niveaux dominance** (S/R) : ce sont les figures les plus fréquentes (102/219) car une zone touchée
  2 fois suffit — c'est le seuil minimum configurable (`levels.min_touches`), volontairement bas ;
* les **doubles sommets/creux** dominent parmi les figures de retournement (87/219) : c'est la figure la plus
  courante sur du Forex en range ;
* les figures rares (biseaux, triangles, canaux : 6/219) sont cohérentes avec des critères stricts (≥ 3 touches
  par ligne, convergence mesurée).

---

## 8. Faux positifs et problèmes connus (assumés)

1. **« Niveaux » très présents.** 102 détections S/R sur 219. Ce sont des niveaux réels (clusters de pivots),
   mais ce ne sont pas des « figures » au sens strict. Réglable par `levels.min_touches` (≥ 2 par défaut).
2. **Sur-détection sur du bruit.** Le contrôle négatif `flat_noise` (marche aléatoire synthétique, tests only)
   produit encore : `flat_noise(120,8,3)` → 1 RESISTANCE ; `flat_noise(300,8,21)` → 2 DOUBLE_TOP confirmés +
   1 DOUBLE_BOTTOM + 1 RESISTANCE. Un bruit très plat peut donc franchir les seuils de retournement.
   Piste : exiger un contexte de tendance pour DTB, comme cela a été fait pour les ETE.
3. **Co-détections auxiliaires** sur un même série synthétique : un scénario ETE peut aussi produire un
   DOUBLE_BOTTOM + S/R ; un drapeau baissier peut être vu comme un biseau ascendant. Le biseau ascendant est
   une lecture légitime de la même géométrie, mais la redondance n'est pas encore arbitrée (pas de règle de
   priorité entre motifs concurrents).
4. **`Rectangle` vs `Support/Résistance`** : la même zone peut être rapportée deux fois (figure + niveaux).
5. **Rapport réel** : ~3 % des bougies D1 de la source sont incohérentes (écart haut/bas jusqu'à 4,6 pips) ;
   les barres sont **conservées telles quelles** et signalées (`quality_warnings`), jamais « corrigées ».
6. **`RETEST_DETECTED` et `PATTERN_EXPIRED`** sont prouvés par des simulations sur fixture et par les tests,
   mais **aucun cas réel** ne s'est présenté sur ce run : ces chemins ne sont donc pas validés en conditions
   réelles (honnêteté > taux de couverture affiché).
7. **Le moteur redémarre à froid** : le registre en mémoire est perdu au redémarrage ; l'historique SQLite
   reste, mais le suivi actif repart de la première bougie clôturée suivante.
8. **Fenêtre = 300 bougies, pas d'historique profond** : une figure plus ancienne n'est pas redétectée (assumé,
   c'est ce qui borne le coût par tour de scanner).

---

## 9. Preuves visuelles (navigateur réel, données réelles)

| fichier | contenu |
|---|---|
| `/home/user/smv-phase2-portrait.png` | portrait 390×844 : bandeau LIVE, prix 1.13430, sélecteurs, graphique |
| `/home/user/smv-phase2-portrait-full.png` | page complète : graphique + structure + **DÉTECTIONS CHARTISTES** (motif, sens, statut, confiance, `6/6 critères validés`, bouton *VOIR SUR LE GRAPHIQUE*) + historique |
| `/home/user/smv-phase2-overlay-portrait.png` | **tracé réel** : contacts « H », neckline/lignes ajustées, niveau RESISTANCE 1.13470 et SUPPORT 1.13417 avec labels |
| `/home/user/smv-phase2-landscape.png` | paysage 844×390 : graphique complet visible, axe de temps lisible |
| `/home/user/smv-phase2-landscape-panel.png` | paysage : panneau de détections |
| `/home/user/smv-phase2-realtime.png` | après reconnexion automatique : liste à jour, bandeau d'événement |

Le dashboard est servi par la même commande que l'API :
`cd backend && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000` → `http://localhost:8000/`.

---

## 10. État des phases

* **Phase 1** : livrée, validée, toujours verte (146 tests).
* **Phase 2** : livrée (139 tests + validations live), **en attente de validation utilisateur**.
* **Phase 3** : **non commencée** — aucune ligne de code Price Action / SMC / ICT n'a été écrite.

### Prochaines étapes recommandées (à décider par l'utilisateur, pas exécutées)

1. **Arbitrer les co-détections** : règles de priorité/exclusion mutuelle entre motifs concurrents
   (drapeau vs biseau, rectangle vs niveaux) — c'est le principal levier de réduction du bruit.
2. **Durcir les retournements sur bruit plat** : exiger un contexte de tendance pour Double Top/Bottom.
3. **Relever `levels.min_touches` à 3** par défaut, ou séparer « niveaux » et « figures » dans l'UI.
4. **Backtest** des détections stockées (le schéma SQLite contient déjà tout : paramètres, mesures, cassure,
   retest) pour mesurer la qualité réelle figure par figure.
5. **Persister/recharger le registre** au redémarrage pour ne pas perdre les formations en cours.
6. Ensuite seulement, ouvrir la suite du programme (Phase 3) si l'utilisateur le demande.
