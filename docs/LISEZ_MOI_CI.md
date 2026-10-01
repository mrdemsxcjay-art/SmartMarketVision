# Comment activer la CI GitHub (contournement d'une permission manquante)

Le jeton utilisé pour publier ce dépôt n'a pas la permission **Workflows**, et GitHub refuse
tout push contenant des fichiers `.github/workflows/*`. Les deux workflows existent donc ici,
en version **texte** :

| Copie texte | Destination |
|---|---|
| `docs/ci_workflow.yml.txt` | `.github/workflows/ci.yml` |
| `docs/pages_workflow.yml.txt` | `.github/workflows/pages.yml` |

## Deux façons de les activer

**A. Donner la permission au jeton (puis je pousse les fichiers moi-même)**
GitHub → Settings → Developer settings → Personal access tokens → votre jeton →
*Permissions* → **Workflows : Read and write** → Save. Prévenez-moi, je pousse les deux fichiers.

**B. Le faire vous-même en 1 minute, sans changer le jeton**
Sur la page du dépôt : onglet **Actions** → *New workflow* → lien **« set up a workflow yourself »**
→ effacez le contenu proposé → collez le contenu de `docs/ci_workflow.yml.txt` → *Commit changes*
→ nommez le fichier `ci.yml` (chemin `.github/workflows/ci.yml`). Répétez pour `pages.yml`.

## Ce que fait la CI

- **`ci.yml`** : à chaque push, 672 tests backend (`pytest`) + 64 tests frontend (`vitest`) +
  build du dashboard. Aucun secret n'est nécessaire : le contrôle échoue volontairement si une
  variable de jeton est présente (en CI, Telegram doit rester `NOT_CONFIGURED`).
- **`pages.yml`** : publication **manuelle** du dashboard statique sur GitHub Pages
  (interface seule : sans backend, les panneaux affichent `DATA UNAVAILABLE` — c'est écrit dans
  la page par un bandeau d'avertissement).

## Rappel

Ces copies texte ne s'exécutent pas : GitHub ne lit que `.github/workflows/`. Elles sont là pour
que vous puissiez activer la CI malgré la permission manquante du jeton.
