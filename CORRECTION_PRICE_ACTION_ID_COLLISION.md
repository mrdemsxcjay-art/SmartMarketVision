# CORRECTION — `UNIQUE constraint failed: pattern_detections.id` (Price Action)

**Objet** : correction ciblée du défaut établi par `AUDIT_PRICE_ACTION_ID_COLLISION.md`.
**Périmètre** : identifiant des détections `REJECTION` / `FAILED_BREAKOUT` + défense en profondeur dans `DetectionRepository.save_many`.
**Fichiers modifiés** : 4 (+ 1 fichier de tests). Aucun seuil, aucun critère, aucune confiance, aucune logique de détection, aucun paramètre, aucun moteur SMC/ICT, aucun fichier Chartiste modifié. Aucune migration destructive. Aucune donnée supprimée. Phase 5 non commencée.

---

## 1. ROOT CAUSE (rappel de l'audit, confirmé par la mesure)

`app/price_action/engine.py::dedup_key` construisait l'identifiant à partir de `symbole|timeframe|pattern|bougie d'ancrage[|extra]` **sans le niveau réel**. Or `REJECTION` et `FAILED_BREAKOUT` sont émis **une fois par niveau chartiste réel** :

* une bougie qui rejette deux supports voisins (1.10000 et 1.10003) ⇒ deux détections légitimes, **un seul id** ;
* deux cassures invalidées sur la même bougie ⇒ même `extra_signature = [breakout_time, candle.time]`, **un seul id**.

`DetectionRepository.save_many` faisait `session.get` → `session.add` : avec `autoflush=False` (config réelle, `app/db/base.py`), les INSERT en attente sont invisibles, donc le doublon intra-lot partait en second INSERT de la même clé primaire ⇒ `IntegrityError` au commit ⇒ **rollback du lot entier**.

La mesure sur données réelles a révélé une **seconde moitié** du défaut : le moteur chartiste publie le même prix **deux fois** (son niveau `NECKLINE`/`CHANNEL`, puis la référence `BREAKOUT` de ce même niveau) — deux références distinctes, mais un id identique. C'est ce qui produisait les 34 collisions résiduelles après la première correction.

---

## 2. CORRECTION

### 2.1 Identifiant (les deux motifs structurels)

`app/patterns/models.py` — `Candidate` reçoit un champ **optionnel** :

```
level_identity: str | None = None
```
Documenté « identité du niveau réel auquel l'événement est rattaché », vide pour tous les autres détecteurs (Chartiste et SMC/ICT ne le renseignent jamais).

`app/price_action/engine.py` — `dedup_key(symbol, timeframe, pattern, candle_time, extra=None, level_ref=None)` :
`level_ref` est ajouté au payload sous la forme `|level=<identité>`. Sans lui, **le comportement est bit pour bit celui d'avant** (vérifié par test).

`app/price_action/detectors/structural.py` — deux helpers, valeurs réelles uniquement :

| Détecteur | Identité du niveau (payload d'id) |
|---|---|
| `REJECTION` | `f"{kind}:{source_id or source}@{round(price, 6)}"` — ex. `SUPPORT:ct_A@1.1`, `BREAKOUT:ct_829c…@1.138665` |
| `FAILED_BREAKOUT` | `f"{level_type}:{parent_id}@{round(level, 6)}"` — ex. `UPPER:ct_up_A@1.1`, `NECKLINE:ct_1c5f…@1.139341` |

* le **type de niveau** distingue les deux références d'un même prix (`NECKLINE` vs `BREAKOUT`) ;
* le **`source_id`** distingue deux niveaux voisins publiés par deux détections différentes ;
* le **prix arrondi à 6 décimales** reprend la convention déjà utilisée par `_levels_from_chartist` pour reconnaître « le même niveau » et absorbe le bruit flottant (1.1393414736 / 1.1393414735794067).

Aucun seuil, aucun critère, aucune confiance, aucune logique de détection n'a changé : seule la clé d'identité.

### 2.2 `save_many` défensivement idempotent

`app/db/repository.py` — le lot est **dédupliqué avant insertion** par la paire `(id, identité stable)` où l'identité stable vient du contenu de l'événement (motif, bougie d'ancrage, dessin, preuves — **jamais** des horodatages de gestion, pour qu'une détection suivie retombe toujours sur la même ligne).

* deux objets **strictement identiques** ⇒ une seule occurrence écrite ;
* deux détections qui ne partagent **que** l'id mais décrivent deux événements différents ⇒ **les deux sont écrites**, leurs clés primaires étant désambiguïsées par leur contenu (`<id>-<hash8>`), de façon déterministe ;
* aucune perte silencieuse : la règle est documentée dans la docstring et testée ;
* conséquence : **plus aucun lot ne peut produire deux INSERT de la même clé**, quel que soit le réglage d'`autoflush` ; la valeur de retour devient « nombre de lignes distinctes écrites » (aucun appelant de production ne l'utilisait).

### 2.3 Compatibilité (anciens IDs / nouveaux IDs)

| | Ancien identifiant | Nouvel identifiant |
|---|---|---|
| Payload | `EURUSD\|M15\|REJECTION\|1760063000` | `EURUSD\|M15\|REJECTION\|1760063000\|level=SUPPORT:ct_A@1.1` |
| `FAILED_BREAKOUT` | `…\|1760063000,1760063900` | `…\|1760063000,1760063900\|level=UPPER:ct_up_A@1.1` |
| Portée du changement | `REJECTION` et `FAILED_BREAKOUT` uniquement | les 11 autres motifs Price Action gardent exactement le même id |

* **Aucune ligne ancienne n'est supprimée ni réécrite** : les 150 lignes `PRICE_ACTION` de la base de développement (dont 14 `REJECTION`) restent en place avec leur ancien id. Test : `test_the_legacy_row_of_a_detection_is_not_duplicated`.
* **Au redéploiement** : le même niveau réel ré-analysé reçoit le **nouvel** id ⇒ une nouvelle ligne apparaît à côté de l'ancienne (qui sort du direct par son cycle de vie normal, `EXPIRED`). Aucune fusion, aucune migration : c'est le comportement déjà en vigueur quand un id disparaît du registre.
* `dedup_key` stocké suit le même changement (il porte le même payload) ; l'API et le front traitent les ids comme des clés opaques.

---

## 3. TESTS AVANT / APRÈS

| Suite | Avant la correction | Après la correction |
|---|---|---|
| `tests/test_price_action_dedup_collision.py` | 13 collectés = **11 passed + 2 xfailed(strict)** | **18 passed** (aucun xfail) |
| Backend — total | 514 passed + 2 xfailed | **521 passed, 0 xfail** (18,5 s) |
| ↳ Phases 1–2 (chartiste, provider, API, stream, sécurité, services) | 285 | **285** |
| ↳ Phase 3 (Price Action) | 116 | **116** |
| ↳ Phase 4 (SMC/ICT) | 102 | **102** |
| ↳ Nouveaux tests de collision | 11 | **18** |
| Frontend `npm test -- --run` | 46 ✓ | **46 ✓** (App 29 + SmcIctPanel 17) |
| Navigateur Phase 3 (coupure + reconnexion incluse) | 42/42 | **42/42** |
| Navigateur Phase 4 (+ 6 captures) | 25/25 | **25/25** |

**Aucun test existant n'a été modifié, supprimé ou désactivé.** Le seul fichier de tests touché est celui créé par l'audit (`test_price_action_dedup_collision.py`) : ses deux `xfail(strict)` qui décrivaient le comportement attendu sont devenus des tests qui passent.

Scénarios exigés, tous couverts :

| Scénario | Test | Résultat |
|---|---|---|
| REJECTION — même bougie + même niveau | `test_same_candle_same_level_keeps_the_same_id` | même id ✓ |
| REJECTION — même bougie + niveaux différents | `test_same_candle_different_level_gives_different_ids` | 2 ids ✓ |
| REJECTION — même prix publié deux fois (NECKLINE + BREAKOUT) | `test_the_same_price_published_twice_gives_two_distinct_ids` | 2 ids ✓ |
| FAILED_BREAKOUT — même bougie + même niveau | `test_same_candle_same_level_keeps_the_same_id` | même id ✓ |
| FAILED_BREAKOUT — même bougie + niveaux différents | `test_same_candle_different_level_gives_different_ids` | 2 ids ✓ |
| Lot `OUTSIDE_BAR + REJECTION A + REJECTION B` | `test_a_healthy_three_detection_batch_is_persisted` | **3 lignes** ✓ |
| Lot avec deux objets strictement identiques | `test_strictly_identical_duplicates_are_written_once` | **1 ligne, aucune erreur** ✓ |
| Lot avec une détection déjà en base | `test_an_already_persisted_detection_is_updated_in_place` | **idempotent, 3 lignes** ✓ |
| Lot forcé « même id, contenus différents » | `test_a_batch_of_same_id_different_events_never_fails` | **2 lignes, aucune erreur, rien de perdu** ✓ |
| Ancienne ligne conservée | `test_the_legacy_row_of_a_detection_is_not_duplicated` | ancienne ligne intacte ✓ |
| Le résultat ne dépend plus d'`autoflush` | `test_the_autoflush_setting_no_longer_hides_anything` | 3 lignes dans les deux cas ✓ |
| Service bout en bout (détections + événements) | `TestServiceEndToEnd` (2 tests) | `service.errors == []` ✓ |

---

## 4. COLLISIONS AVANT / APRÈS

Protocole identique à celui de l'audit : 10 paires × M15/H1/H4/D1, fenêtre de **300 bougies réelles**, **pas de 1 bougie**, registre réinitialisé à chaque fenêtre. L'« AVANT » est reconstruit exactement (identités sans niveau + `save_many` d'origine) pour que la comparaison porte sur le même protocole.

| Mesure | AVANT | APRÈS |
|---|---|---|
| Fenêtres analysées | 1947 | **1947** |
| Détections produites | 11 187 | **11 187** |
| **Fenêtres en collision d'id** | **233 (12,0 %)** | **0** |
| **Ids en collision** | **241** — REJECTION 137, FAILED_BREAKOUT 104 | **0** |
| ↳ M15 | 207 / 1621 | **0 / 1621** |
| ↳ H1 | 8 / 116 | **0 / 116** |
| ↳ H4 | 2 / 104 | **0 / 104** |
| ↳ D1 | 16 / 106 | **0 / 106** |
| Erreurs de persistance | **10 368** | **0** |
| Lots en échec (rollback) | **1715 fenêtres** | **0** |
| Lignes `pattern_detections` écrites | 1169 | **1499** |
| Lignes `market_events` | 18 789 | 19 093 |

**Objectif atteint : aucune collision légitime REJECTION / FAILED_BREAKOUT sur les données réelles**, et plus aucune erreur de persistance.

## 5. DONNÉES RÉELLES

EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD, EURGBP, EURJPY, GBPJPY × M15 / H1 / H4 / D1, bougies réellement stockées dans `data/smart_market_vision.db` (7 058 bougies), fenêtres de 300 bougies glissantes (pas de 1). Répartition des 11 187 détections mesurées : INSIDE_BAR 2357, FAILED_BREAKOUT 1849, DOJI 1638, OUTSIDE_BAR 1306, BULLISH_PIN_BAR 783, BEARISH_ENGULFING 767, BULLISH_ENGULFING 736, BEARISH_PIN_BAR 600, REJECTION 443, HAMMER 351, SHOOTING_STAR 223, CONSOLIDATION 81, IMPULSION 53. Aucune donnée synthétique n'a été utilisée (les fixtures synthétiques restent réservées aux tests).

## 6. PERSISTENCE

* 18 tests dédiés (classe `TestSaveManyDeduplication` + `TestServiceEndToEnd`), tous verts.
* Comportement sur un lot de 3 (`OUTSIDE_BAR` + 2 `REJECTION`) : **3 lignes**, `service.errors == []`.
* Doublons stricts : **1 ligne**, aucune `IntegrityError`.
* Détection existante : mise à jour en place, **aucun doublon**, aucun compteur qui dérive.
* Défense en profondeur : un lot forcé à « même id, contenus différents » écrit **2 lignes** au lieu de faire échouer les 3 — aucune détection perdue.
* Ancienne ligne (id pré-correction) : conservée, non réécrite, non dupliquée.
* Aucune perte de lot mesurable sur les 1947 fenêtres réelles : `0` erreur, `0` rollback.

## 7. LIVE

Serveur réel + scanner sur données réelles (Yahoo), `SCANNER_TICK_SECONDS=15`, 10 paires.

| Mesure | Valeur |
|---|---|
| Session 1 : 07:49:24 → 07:57:12 (coupure volontaire pour le test navigateur) | **28 ticks**, 0 erreur scanner |
| Session 2 (après reconnexion, pendant les runs navigateur) | 4 ticks, 0 erreur |
| `IntegrityError` | **0** |
| Lots perdus | **0** |
| Détections PA persistées pendant le live | **74 lignes, 74 ids distincts, 74 `dedup_key` distincts** |
| Ids désambiguïsés par la défense (`<id>-<hash>`) | **0** (plus aucune collision à rattraper) |
| Dont motifs du correctif | **2 `REJECTION`**, **7 `FAILED_BREAKOUT`** |
| Événements `PRICE_ACTION_DETECTED` | 148 (= 2 sessions × 1 publication) → **74 ids distincts** |
| Cohérence lignes ↔ événements | **0 ligne sans événement, 0 événement sans ligne** (ensembles d'ids identiques) |
| Registre moteur vs base | **74 = 74** |
| `GET /api/events/recent` | **HTTP 500** — problème collatéral, voir §11 |

Vérification résiduelle : aucun calque/trading, `trading_signal: false`, Telegram `NOT_CONFIGURED` (inchangés).

## 8. NAVIGATEUR

| Script | Résultat | Couverture |
|---|---|---|
| `smv_phase3_browser.py` (via `run_phase3_with_outage.py`) | **42/42** | dashboard réel, Price Action, SMC/ICT, changement de paire, changement d'unité de temps, WebSocket, **coupure + reconnexion** (LIVE → RECONNECTING → LIVE, sans rechargement de page), desktop 1440×900, mobile portrait 390×844, mobile paysage 844×390, absence d'instruction de trading, 0 erreur console hors coupure volontaire |
| `smv_phase4_browser.py` | **25/25** | panneau SMC/ICT (47 objets), cohérence UI ↔ API (29 prix, 0 inconnu), mobile 390×844 et 844×390 (aucun débordement, commandes ≥ 32 px), 0 erreur console |
| Captures | 6 régénérées | `reports/screenshots/phase4_{desktop,desktop_viewport,mobile_portrait,mobile_portrait_viewport,mobile_landscape,mobile_landscape_viewport}.png` |

## 9. IMPACT SUR PHASE 3

* Détecteurs, seuils, critères, confiances, paramètres : **inchangés** (aucune ligne de logique modifiée ; seules les clés d'identité).
* 116 tests Price Action verts, dont `test_price_action_structure.py` (39) et `test_price_action_pipeline.py` (33) **non modifiés**.
* Seul changement observable : les ids de `REJECTION` / `FAILED_BREAKOUT` (et le `dedup_key` stocké, qui porte le même payload). Les autres motifs gardent exactement leurs ids.
* Effet de bord **positif et attendu** : les détections auparavant perdues sont désormais persistées (lignes 1169 → 1499 sur le protocole réel) ; le dashboard live était déjà correct (registre mémoire).
* Les deux paires-sœurs qui se confondaient produisent maintenant **deux lignes distinctes** au lieu d'une écriture en échec ou d'un écrasement silencieux.
* Point de vigilance (déjà en place, inchangé) : `REJECTION` s'arrête à 2 candidats par bougie (`if len(candidates) >= 2: break`) — le correctif ne touche pas cette limite.
* Navigateur Phase 3 : **42/42**, reconnexion incluse.

## 10. IMPACT SUR PHASE 4

* **Aucun fichier de `app/smc_ict/` modifié**, aucun paramètre SMC/ICT touché, aucun second Event Bus, aucun second moteur de pivots.
* `app/patterns/models.py` (fichier partagé) reçoit un champ **optionnel et documenté** (`level_identity`, défaut `None`) : Price Action seul le renseigne. Le Chartiste garde son identité par `pivot_signature()` (qui n'y touche pas) et SMC/ICT garde `smc_<sha1[:16]>` sur son propre `SmcCandidate` — **comportement bit pour bit identique**, corroboré par la mesure (0 % de collision SMC/ICT avant comme après).
* 102 tests SMC/ICT verts (`test_smc_ict_structure` 27, `test_smc_ict_detectors` 41, `test_smc_ict_engine` 34), **non modifiés**.
* Navigateur Phase 4 : **25/25** ; panneau SMC/ICT et captures inchangés.

## 11. PROBLÈMES COLLATÉRAUX

**Non corrigés — hors périmètre de cette correction, signalés séparément comme demandé.**

### P1 — `metadata_json` tronqué à 4 000 caractères ⇒ `/api/events/recent` renvoie HTTP 500

* `EventRepository.save` fait `json.dumps(event.metadata)[:4000]` (`repository.py` l. 167) : le JSON est coupé en pleine chaîne.
* Constaté en direct pendant le live : `GET /api/events/recent` → **HTTP 500**, `json.decoder.JSONDecodeError: Unterminated string starting at: line 1 column 3999 (char 3998)` (`api/system.py:140` → `repository.py:187`).
* **Non aggravé par la correction** : avant le live, 1 406 / 1 406 événements `PRICE_ACTION_DETECTED` tronqués (**100 %**) et 8 358 / 8 708 lignes au total (96,0 %) ; après, 1 480 / 1 480 (**100 %**) et 9 148 / 9 511 (96,2 %). La proportion est identique — la troncature est structurelle et dépend de la taille du payload, que le correctif ne modifie pas (seul l'id change, sur 16 caractères hexadécimaux).
* Impact visible : la route REST est inutilisable quelle que soit la donnée affichée ; le dashboard n'appelle pas cette route (il consomme le WebSocket) et n'est donc pas affecté.
* Correction suggérée pour une tâche distincte : troncature consciente du JSON (ou colonne non bornée) + lecture tolérante dans `recent()`.

### P2 — Le même prix publié deux fois par le chartiste produit deux détections `REJECTION`

* Le chartiste publie un niveau, puis la référence `BREAKOUT` de ce même niveau (même `source_id`, même prix) : Price Action en fait **deux** détections `REJECTION` (deux références de niveau différentes).
* Après correction elles ont deux ids et **deux lignes** : plus rien n'est confondu ni perdu, mais la même observation apparaît deux fois. Aucune fusion silencieuse n'a été introduite (ce serait une perte de donnée).
* Un dédoublonnage en amont (un seul `LevelRef` par niveau réel) relèverait de la **logique de détection/du choix des niveaux** : explicitement hors périmètre ici. À arbitrer dans une phase ultérieure si cette redondance est jugée indésirable.

---

## SYNTHÈSE

| Exigence | État |
|---|---|
| REJECTION : niveau réel dans l'id | ✅ `kind:source_id@prix` |
| FAILED_BREAKOUT : niveau réellement cassé dans la signature | ✅ `level_type:parent_id@prix` |
| `save_many` défensivement idempotent (lot dédupliqué avant insertion) | ✅ aucune collision de clé possible |
| Comportement documenté (« conserver une seule occurrence », jamais d'échec de lot) | ✅ docstring + 18 tests |
| Compatibilité anciens ids (rien supprimé, rien réécrit, pas de migration) | ✅ test dédié |
| Non-régression Phases 1→4 + nouveaux tests | ✅ 521 backend / 46 frontend / 42+25 navigateur |
| Vérification sur données réelles (10 paires × 4 UT × 300) | ✅ 0 collision, 0 erreur, 0 rollback |
| Test live (aucune IntegrityError, aucune perte, cohérence événements/détections) | ✅ 32 ticks, 74 = 74, 0 écart |
| Interdits (Phase 5, SMC/ICT, Chartiste, paramètres PA, Telegram, BUY/SELL/ENTRY/SL/TP, migration destructive) | ✅ tous respectés |
