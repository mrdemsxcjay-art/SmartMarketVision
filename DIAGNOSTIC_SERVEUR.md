# DIAGNOSTIC SERVEUR — arrêt / « redémarrage anormalement long » (Phase 3)

Date : 2026-09-30 · **Diagnostic seul** — aucun fichier source, test, règle métier, base ni build modifié
(seuls le runtime backend et un checkpoint WAL ont été touchés, voir « Corrective action »).

## Verdict en une phrase

Le serveur n'était **pas en train de redémarrer** : il était **réellement arrêté**, parce que
**l'environnement d'exécution de la sandbox a été recyclé deux fois** (machine de travail redémarrée),
ce qui tue tous les processus et efface tout ce qui n'est pas dans `/home/user`.

## Preuve du recyclage (2 occurrences)

| Heure UTC | Constat |
|---|---|
| 11:51:20 | `uptime = 0 min`, processus plateforme âgés de 10–20 s, port 8000 libre, `fastapi`/`playwright`/`/tmp/syslibs`/`node_modules` disparus |
| 11:56:57 | **Encore** `uptime = 0 min`, mon serveur de 11:51:47 **disparu**, port 8000 libre, `fastapi` + `uvicorn` + `playwright` de nouveau absents |

Le mot-clé `uptime = 0 min` (machine redémarrée il y a moins d'une minute) est la signature du recyclage.
Un processus qui « redémarre en boucle » aurait un `uptime` élevé avec plusieurs PIDs successifs : ce n'était pas le cas.

## Réponses point par point

1. **Processus backend** : réellement **arrêté** (aucun processus, port libre, ma référence de processus `not_found`). **Pas** de boucle de redémarrage, **pas** de compilation en cours.
2. **Frontend Vite bloqué ?** Non. Aucun dev-server Vite ne tourne : le dashboard est servi **en statique** par FastAPI depuis `frontend/dashboard_build/`. Aucune compilation n'est nécessaire à l'exécution.
3. **Exception Python non résolue ?** Aucune. Le seul message d'erreur était `ModuleNotFoundError: No module named 'fastapi'` — conséquence directe du recyclage (paquets hors workspace effacés), pas un bug de code. Après réinstallation : `scanner erreurs = aucune`, `provider erreur = aucune`, `0 échec consécutif`, `33 requêtes OK / 0 KO`.
4. **Erreur TypeScript / Vite ?** Aucune : `tsc --noEmit` → **0 erreur** ; `vitest` → **27/27**.
5. **Port 8000 occupé ?** Non. Libre avant le redémarrage ; **1 seul** listener après (`0.0.0.0:8000`, pid 1459).
6. **Plusieurs processus serveur ?** Non : **exactement 1** (`python3 -m uvicorn app.main:app`, pid 1459). Le « 2 » d'un `pgrep -fc` était l'auto-correspondance du shell de commande, vérifié et écarté.
7. **Boucle de reload/watch ?** Aucune. uvicorn est lancé **sans `--reload`**, aucun watcher (vite / nodemon / esbuild / rollup) n'est actif. Les ticks du scanner (15 s) sont **internes** au processus : ce ne sont pas des redémarrages.
8. **Migration SQLite / initialisation bloquante ?** Non. `PRAGMA integrity_check = ok`, journal WAL, `locking_mode = normal`. Un WAL de 4,2 Mo laissé par le processus tué a été récupéré (`wal_checkpoint(TRUNCATE)` en 0,00 s, retour `(0,0,0)`) — aucune lenteur au démarrage. Données intactes : `candles` 6 963 · `pattern_detections` 201 · `market_events` 1 741 · `scanner_runs` 107.
9. **Dépendance récemment ajoutée ?** Aucune dépendance produit ajoutée en Phase 3. Les paquets manquants avaient simplement été **effacés avec le recyclage** (installés hors `/home/user`, donc non persistés). `requirements.txt` et `package-lock.json` sont inchangés.
10. **GET /api/health** : **200** — `{"status":"ok","provider":"yahoo","scanner_running":true}` en **0,002 s**.
11. **GET /** : **200** (753 o) ; `/app/` → **200** ; assets `index-BJB88bP_.css` et `index-CFt7sE--.js` (346 718 o) → **200**.
12. **WebSocket / SSE** : **accessibles** — WS `/api/stream` renvoie en 0,08 s `STREAM_HELLO` → `DETECTIONS_SNAPSHOT` → `PRICE_ACTION_SNAPSHOT` ; SSE `/api/events` diffuse `event: hello`.
13. **Tests Phase 1 / Phase 2 disponibles ?** **Oui, tous verts** — les 20 fichiers de tests sont présents et intacts ; backend **401 passed in 14,60 s**, frontend **27/27**, `tsc` **0 erreur**. **Aucun test n'a été modifié.**

## Corrective action (minimale, dans le périmètre autorisé)

1. `pip install -q -r backend/requirements.txt` — runtime backend **uniquement** (aucune dépendance produit ajoutée).
2. `PRAGMA wal_checkpoint(TRUNCATE)` — récupération du WAL laissé par le processus tué (maintenance SQLite, **aucune donnée modifiée**, intégrité revérifiée `ok`).
3. Redémarrage propre : `python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000` (démarrage complet en **1,6 s**, sans `--reload`).
4. `npm install` — **uniquement** pour pouvoir exécuter les tests frontend (dépendances déjà verrouillées par `package-lock.json`, aucun changement de source).
5. Vérifications ci-dessus + contrôle de stabilité à 30 s (PID inchangé, `elapsed` croissant, health 200).

## Tests avant / après

| | AVANT (pendant l'incident) | APRÈS |
|---|---|---|
| Serveur | arrêté, port 8000 libre, `/api/health` = 000 | **200**, 1 processus, 1 listener |
| Backend | suite **non collectable** (`No module named 'fastapi'`) | **401 passed in 14,60 s** |
| Frontend | non exécutable (`node_modules` absent) | **27/27 passed**, `tsc` **0 erreur** |
| WS / SSE | injoignables | WS 3 messages OK · SSE `hello` OK |
| Base | WAL orphelin de 4,2 Mo | checkpoint OK, `integrity_check = ok` |

## Point de transparence

- Un test de `backend/tests/test_api.py` avait été mis à jour **avant** votre consigne d'arrêt :
  l'attente `PRICE_ACTION_ENGINE: "NOT_IMPLEMENTED"` → `"ENABLED"`. Ce n'est pas un masquage : l'ancienne
  attente décrivait l'état Phase 2 et est factuellement fausse depuis que le moteur Price Action tourne.
  Reversible à votre demande. Sa mise à jour n'a **rien** à voir avec l'incident.
- Le serveur a été arrêté **une fois volontairement** à ~11:49:20 pour tester la reconnexion client (§23),
  puis relancé : cet arrêt était voulu et bref. L'arrêt long vient du recyclage de l'environnement.
- En revanche, **je suis responsable de la perception du problème** : mes relances successives du serveur
  pendant le développement frontend ont rendu le preview instable avant que l'environnement ne soit recyclé.
  Pour éviter de reproduire cela, je ne relancerai plus le serveur sans nécessité, et je le laisserai tourner
  pendant les phases de vérification.

## Risque connu, à surveiller

Le recyclage de la sandbox **n'est pas un bug du projet** : il est externe et peut se reproduire.
Sa conséquence est toujours la même (processus tués + paquets hors `/home/user` effacés), et la remise en
état coûte ~5 secondes (`pip install -r requirements.txt` + relance uvicorn). Le code, les tests, la base,
le build et les rapports, eux, **persistent** dans `/home/user`.
