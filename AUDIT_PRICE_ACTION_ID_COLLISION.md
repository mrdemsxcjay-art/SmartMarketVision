# AUDIT CIBLÉ — `UNIQUE constraint failed: pattern_detections.id`

**Objet** : préexistant observé en Phase 3 (moteur Price Action), resté non expliqué.
> **MISE À JOUR (2026-10-01)** : la correction ciblée a été appliquée et validée depuis — voir
> `CORRECTION_PRICE_ACTION_ID_COLLISION.md`. Ce document reste le relevé d'audit d'origine
> (état du code AVANT correction).

**Nature** : audit en **lecture seule**. Aucun détecteur, paramètre, moteur, dashboard ou test existant n'a été modifié. **Aucune correction appliquée** (conformément à la consigne).
**Seul ajout** : `backend/tests/test_price_action_dedup_collision.py` (13 tests, fichier nouveau).
**Date** : 2026-09-30 · **Environnement** : base de développement lue en `mode=ro`, sondes sur bases temporaires.

---

## 1. ROOT CAUSE

L'identifiant d'une détection Price Action est construit par `app/price_action/engine.py::dedup_key` :

```
pa_<sha1("SYMBOL|TIMEFRAME|PATTERN|<bougie d'ancrage>[|extra_signature]")[:16]>
```

Deux détecteurs structurels émettent **une détection par niveau chartiste réel** :

| Détecteur | Fichier | Ce que la clé contient | Ce qu'elle **ne** contient pas |
|---|---|---|---|
| `REJECTION` | `detectors/structural.py` | paire, UT, motif, bougie du rejet | **le prix du niveau rejeté**, sa source, sa distance |
| `FAILED_BREAKOUT` | `detectors/structural.py` (l. 574) | + `extra_signature = [breakout_time, candle.time]` | **le niveau cassé** (deux niveaux cassés sur la même bougie ⇒ même signature) |

Conséquence : une seule bougie qui rejette **deux niveaux réels distincts** (ex. 1.10000 et 1.10003, ou 1.1393414736 / 1.1393414735794067) — ou qui invalide **deux cassures distinctes** — produit deux détections **légitimement différentes** (niveau, écart, critères, confiance) portant **le même identifiant**. Ce ne sont pas deux émissions du même événement : c'est l'ID qui n'est pas discriminant, pas le moteur qui dédouble.

Le défaut devient une **erreur bloquante** dans la couche de persistance :
`DetectionRepository.save_many` fait `session.get(id)` → `session.add(...)` pour chaque détection, et `app/db/base.py` configure `SessionLocal(autoflush=False)`. Les INSERT en attente **ne sont donc pas visibles** du `session.get` : le second élément de la paire est considéré comme neuf et un second INSERT de la même clé primaire part au commit ⇒ `UNIQUE constraint failed: pattern_detections.id` ⇒ **rollback de la transaction entière**.

Répartition des responsabilités : **défaut de conception d'ID côté Price Action**, **révélé** (non créé) par la couche de persistance qui n'est pas idempotente sur un lot. Aucun autre moteur n'est concerné (mesuré : Chartiste 0 %, SMC/ICT 0 % sur 199 fenêtres réelles).

---

## 2. REPRODUCTION

### 2.1 Test ciblé (seul ajout autorisé)

`backend/tests/test_price_action_dedup_collision.py` — **11 passed, 2 xfailed (strict)**, 0.53 s.

Structure du fichier :
- `TestReproduction` (6 tests) — le défaut existe : deux rejets, **un seul id** ; id déterministe et **indépendant du niveau** ; `FAILED_BREAKOUT` identique ; collision répétée à chaque tick ; registre écrasant la première.
- `TestPersistenceImpact` (5 tests) — `save_many` lève `IntegrityError: UNIQUE constraint failed: pattern_detections.id` et **`count() == 0`** ; le service journalise sans interrompre le scanner ; asymétrie détections/événements ; **contrôle** : un lot sain s'écrit et se met à jour sans doublon ; `autoflush=True` masque le défaut.
- `TestExpectedBehaviour` (2 tests `xfail(strict=True)`) — unicité des IDs dans un lot et persistance du lot entier. **Ils échouent aujourd'hui**, donc la suite reste verte ; le jour de la correction ils passeront en `XPASS` et `strict` forcera la mise à jour du marqueur.

Aucun test existant n'a été modifié.

### 2.2 Scénario exact, étape par étape

```
bougie : open 1.10020 / high 1.10030 / low 1.09990 / close 1.10060   (mèche sous support, clôture au-dessus)
niveaux chartistes réels : SUPPORT 1.10000 (ct_A, âge 0) et SUPPORT 1.10003 (ct_B, âge 0)

1. moteur PA      -> 3 détections : OUTSIDE_BAR pa_f6bc560a736c345a (83,3)
                                     REJECTION    pa_7ecaf0448d672127 (100,0)  niveau 1.10000
                                     REJECTION    pa_7ecaf0448d672127 ( 77,8)  niveau 1.10003  <-- même id
2. save_many      -> 2 INSERT sur la clé pa_7ecaf0448d672127 dans la même transaction
3. commit         -> sqlite3.IntegrityError: UNIQUE constraint failed: pattern_detections.id
4. rollback       -> pattern_detections : 0 ligne (l'OUTSIDE_BAR sain est perdu aussi)
5. événements     -> market_events +2 (transaction séparée) et registre en mémoire à jour
6. tick suivant   -> les 2 détections sont toujours suivies => mêmes 2 ids => échec à nouveau
```

Recomposition vérifiée de l'id : `"pa_" + sha1("EURUSD|M15|REJECTION|1760063000")[:16]` = `pa_7ecaf0448d672127` — ni le niveau, ni la source, ni la confiance n'entrent dans la clé.

### 2.3 Fréquence mesurée sur bougies **réelles** (base `data/smart_market_vision.db`, 10 paires × 4 UT)

Fenêtre glissante de 300 bougies, **pas de 1 bougie**, 1947 fenêtres analysées :

| Unité de temps | Fenêtres en collision |
|---|---|
| M15 | **207 / 1621 = 12,8 %** |
| H1 | 8 / 116 = 6,9 % |
| D1 | 16 / 106 = 15,1 % |
| H4 | 2 / 104 = 1,9 % |
| **Total** | **233 / 1947 = 12,0 %** |

241 identifiants en collision : **REJECTION 137, FAILED_BREAKOUT 104**.
Durée des épisodes consécutifs : médiane **1 bougie**, maximum **45 bougies** (110 épisodes).
Mesure antérieure sur 651 fenêtres : 11,1 % — cohérent.

### 2.4 Les 7 vérifications demandées

| # | Question | Réponse mesurée |
|---|---|---|
| 1 | Le même événement est-il généré deux fois ? | **Non.** Ce sont deux détections réellement distinctes (deux niveaux réels) qui reçoivent le même ID. Aucune double émission. |
| 2 | L'ID est-il déterministe ? | **Oui.** Stable d'un run à l'autre, recomposable à la main (test dédié). |
| 3 | Deux processus/threads écrivent-ils en même temps ? | **Non.** Un seul `uvicorn` sans `--reload` ni `--workers`, scanner = une seule `asyncio.create_task`, toutes les routes API sont `async def` (aucun handler en threadpool), un seul écrivain de `pattern_detections` par moteur. |
| 4 | Une reconnexion WebSocket provoque-t-elle une réémission ? | **Non.** `stream.py::_price_action_snapshot` ne fait que lire le registre et l'historique. |
| 5 | Le scanner relance-t-il une détection déjà persistée ? | **Non.** Réanalyser une détection suivie met à jour sa ligne (`session.get` la retrouve). Le défaut est **purement intra-lot**. |
| 6 | Price Action ou couche persistence ? | **Price Action** (schéma d'ID non discriminant), **révélé** par la persistance (`save_many` non idempotent + `autoflush=False`). Le même `save_many` ne casse jamais pour Chartiste ni SMC/ICT. |
| 7 | Bénin ou perte d'une détection valide ? | **Non bénin** (voir §3). |

---

## 3. IMPACT

1. **Perte du lot entier, pas du seul doublon.** Le rollback annule la transaction : *toutes* les détections du tick disparaissent de `pattern_detections`, y compris celles sans problème. Démonstration dans le test : lot de 3 → 0 ligne.
2. **Perte cumulée sur toute la durée de l'épisode.** Tant que la paire en collision reste dans la fenêtre suivie, chaque tick échoue. Épisodes mesurés jusqu'à **45 bougies** consécutives ⇒ plusieurs dizaines de lots perdus d'affilée (historique, replay, statistiques, compteurs), alors que l'API/dashboard continuent d'afficher ces détections (registre mémoire intact).
3. **Divergence base ↔ temps réel.** `market_events` conserve les événements (transaction séparée) mais `pattern_detections` non : la base de développement contient **1406 événements `PRICE_ACTION_DETECTED` pour 150 lignes `pattern_detections`** (le ratio n'est pas une mesure de perte, les ré-émissions sont comptées, mais l'écart de nature est bien là).
4. **Amplitude estimée** : ~12 % des fenêtres réelles contiennent au moins une collision ; chaque épisode coûte ≥ 2 détections (la paire) **plus toutes les autres du même lot**.
5. **Ce qui n'est PAS touché** : le dashboard live, les détections affichées, les paramètres validés, le moteur SMC/ICT, Chartiste, et aucune exécution d'ordre (aucune n'existe dans le projet).
6. **Collatéral associé (hors cause, non corrigé)** — `EventRepository.save` tronque `metadata_json[:4000]` (`repository.py` l.167) : **100 % (1406/1406) des événements `PRICE_ACTION_DETECTED`** et 8358/8708 lignes de `market_events` sont tronquées en plein JSON. Vérifié sur le serveur en marche : `GET /api/events/recent` → **HTTP 500**, `json.decoder.JSONDecodeError: Expecting value: line 1 column 4001`. Le dashboard n'appelle pas cette route (il consomme le WebSocket) : il est donc intact, mais la route REST est cassée pour toutes les données existantes.

---

## 4. PROPOSITION DE CORRECTION (non appliquée)

**Minimale, ciblée sur le schéma d'ID** — rendre l'ID discriminant sans toucher aux seuils ni aux détecteurs :

1. `detectors/structural.py` → `REJECTION` : ajouter au payload d'ID le niveau réellement testé (prix du niveau arrondi à la tolérance, ou `source_id` du niveau + prix). Deux supports distincts produisent alors `pa_…A` et `pa_…B`.
2. `detectors/structural.py` → `FAILED_BREAKOUT` (l. 574) : ajouter au `extra_signature` l'identité du niveau cassé (niveau/parent), pas seulement `[breakout_time, candle.time]`.
3. **Défense en profondeur recommandée** (indépendante du point 1) : dans `DetectionRepository.save_many`, dédupliquer par ID à l'intérieur du lot (`session.get` ne voyant pas les INSERT en attente, un doublon intra-lot restera toujours possible) — fusionner ou journaliser explicitement au lieu de faire échouer toute la transaction. Bénéfice : un futur motif émettant deux fois la même clé ne fera plus perdre un lot complet.

**Hors périmètre de cette correction** : la troncature `metadata_json[:4000]` (à traiter séparément : troncature consciente du JSON ou colonne TEXT non bornée + `recent()` tolérant). Elle est signalée, pas corrigée.

---

## 5. RISQUE PHASE 3 (si la correction est appliquée plus tard)

| Risque | Niveau | Détail |
|---|---|---|
| **Changement des IDs `REJECTION`/`FAILED_BREAKOUT`** | **Le risque principal** | Les IDs sont les clés du registre mémoire, de la déduplication, de l'historique, des liens `parent_detection_id` et du front. Après déploiement, les lignes existantes gardent leur ancien ID : les détections en cours seront re-créées sous un nouvel ID (une ligne « orpheline » par détection live au moment du redéploiement). Acceptable pour une base de dev ; à décider pour une base de production (purge ou migration). |
| Comportement des détecteurs | Nul | Aucun motif, aucun seuil, aucun critère, aucune confiance modifiés. Seule la clé change. |
| Volume de détections | Nul | Le correctif ne fait qu'**arrêter de fusionner** deux détections qui existaient déjà en mémoire. Les compteurs pourraient **augmenter** en base (les couples auparavant perdus sont enfin persistés) — c'est le comportement correct, pas une régression. |
| Autres moteurs | Nul | Chartiste et SMC/ICT ont mesuré 0 % de collision ; la défense dans `save_many` est générique et n'altère aucun ID. |
| Tests Phase 3 | Faible | Aucun test existant ne dépend d'un ID `pa_…` figé (les IDs du nouveau fichier d'audit, eux, seront à basculer de `xfail` à `pass`). À vérifier par une passe complète de la suite. |
| Dashboard / front | Faible | Le front utilise les IDs comme clés de liste : des IDs stables plus discriminants sont strictement plus sûrs. |

---

## 6. TESTS

| Suite | Résultat |
|---|---|
| `tests/test_price_action_dedup_collision.py` (nouveau) | **11 passed, 2 xfailed (strict)** — 0.53 s |
| Suite backend complète | **514 passed, 2 xfailed** — 18,55 s (503 avant cet audit + 11) |
| Autres moteurs (lecture seule) | 199 fenêtres : Chartiste 0 %, SMC/ICT 0 %, Price Action 15 (7,5 %) |

Aucun test existant modifié, aucun test supprimé, aucun contrôle désactivé, aucun PASS obtenu artificiellement.

---

## 7. FICHIERS CONCERNÉS

**Chaîne du défaut (non modifiés)**

| Fichier | Rôle dans le défaut |
|---|---|
| `backend/app/price_action/engine.py` | `dedup_key` → `pa_<sha1[:16]>` (id non discriminant) |
| `backend/app/price_action/detectors/structural.py` | l. 574 `extra_signature=[ref.breakout_time, candle.time]` ; 1 candidat par niveau réel pour `REJECTION` |
| `backend/app/services/price_action.py` | `_persist` : échec capturé dans `self.errors`, scanner maintenu en marche |
| `backend/app/db/repository.py` | `save_many` (`session.get` → `session.add`, non idempotent intra-lot) ; l. 167 `metadata_json[:4000]` (collatéral) |
| `backend/app/db/base.py` | `SessionLocal(autoflush=False)` — condition d'apparition de l'erreur |
| `backend/app/api/stream.py` | `_price_action_snapshot` (lecture seule — hors cause) |

**Créé lors de cet audit (seul ajout)**

- `backend/tests/test_price_action_dedup_collision.py`

**Ce rapport**

- `AUDIT_PRICE_ACTION_ID_COLLISION.md`

**État du serveur** : `uvicorn :8000` n'était pas relancé après le recyclage ; il a été redémarré pendant l'audit pour vérifier le collatéral (`/api/health` = 200). Base de développement jamais écrite : lectures `mode=ro`, sondes sur bases temporaires.

**Aucune correction n'a été appliquée lors de cet audit** (la correction ciblée a été faite plus tard, voir `CORRECTION_PRICE_ACTION_ID_COLLISION.md`). **Phase 5 non commencée.**
