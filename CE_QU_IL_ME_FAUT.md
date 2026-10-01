# CE DONT J'AI BESOIN POUR POUSSER ET POUR TESTER TELEGRAM

Résumé en une page. Les deux sujets sont **indépendants** : vous pouvez faire le push sans
me donner aucun secret, et tester Telegram sans passer par GitHub.

---

## 1. Pousser le projet sur GitHub — trois façons, dont deux sans me donner de secret

### A. Sans rien me transmettre (recommandé) — bundle prêt

Un fichier de **15 Mo** contient tout le dépôt (210 fichiers, 2 commits, branche `main`,
historique compris) :

```
/home/user/smart-market-vision.bundle
```

Téléchargez-le, puis sur **votre machine** :

```bash
# 1) créez un dépôt VIDE sur github.com (bouton "New repository", sans README)
# 2) restaurez le projet depuis le bundle
git clone smart-market-vision.bundle smart-market-vision
cd smart-market-vision

# 3) pointez vers votre dépôt et poussez (Git vous authentifie : navigateur, trousseau, SSH)
git remote set-url origin https://github.com/<votre-compte>/smart-market-vision.git
git push -u origin main
```

Ou, si vous avez déjà un dossier local : `./PUSH_VERS_GITHUB.sh <url-du-depot>` (le script
vérifie d'abord qu'aucun `.env` ni jeton ne part, puis pousse).

### B. Je pousse depuis cet espace — ce qu'il me faut alors

| Élément | Pourquoi | Sensibilité |
|---|---|---|
| **URL du dépôt vide** (`https://github.com/<compte>/<dépôt>.git`) | destination | aucune |
| **Un jeton d'accès GitHub *fine-grained*** | authentifier le push | **secret** |

Réglages à choisir pour ce jeton : *Repository access* = **ce dépôt uniquement**,
*Permissions → Contents* = **Read and write**, **expiration la plus courte possible** (7 jours).
Ne cochez rien d'autre. Prévenez-moi quand le push est fait : **révoquez-le immédiatement**
(Settings → Developer settings → Personal access tokens → Delete).

> **Ce que je ne veux pas** : votre mot de passe GitHub, un code 2FA, ou un jeton *classic*
> avec les droits sur tous vos dépôts. Ce n'est pas nécessaire et c'est dangereux.

### C. Encore plus simple

Créez le dépôt vide, puis utilisez l'interface web de GitHub (« Add file → Upload files ») ou
GitHub Desktop avec le dossier du projet. Aucune ligne de commande, aucun secret partagé.

---

## 2. Envoyer un message de test sur le bot — ce qu'il me faut

**Vérifié à l'instant depuis cet espace** : l'API Telegram est joignable
(`https://api.telegram.org/` → HTTP 200 ; un faux jeton renvoie bien `401 Unauthorized`).
Donc **je peux envoyer le vrai message de test depuis ici** dès que j'ai les deux valeurs.

| Valeur | Où la trouver | Sensibilité |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather → `/newbot` (ou `/mybots` → API Token) | **secret** : à traiter comme un mot de passe |
| `TELEGRAM_CHAT_ID` | conversation avec votre bot, ou `tools/telegram_setup.py --list-chats` | peu sensible (identifiant numérique) |

### Comment me les transmettre — par ordre de sécurité

1. **Pièce jointe `.env`** *(le mieux si vous voulez que je le fasse)* : créez un fichier texte
   nommé `.env` contenant exactement ces deux lignes, et **joignez-le** à votre message :
   ```
   TELEGRAM_BOT_TOKEN=votre-jeton
   TELEGRAM_CHAT_ID=votre-chat-id
   ```
   Le contenu d'une pièce jointe n'apparaît pas dans le texte de la conversation. Je l'écrirai
   dans `smart-market-vision/.env` (permissions `600`, déjà exclu de Git).

2. **Dans l'espace de travail** *(équivalent)* : déposez le `.env` dans les fichiers du projet,
   je le récupère.

3. **Collé dans le message** : ça fonctionne, mais le jeton resterait dans l'historique de la
   conversation. Si vous choisissez cette voie, **révoquez-le dès le test terminé**
   (@BotFather → `/revoke` → nouveau jeton), et sachez que je ne l'afficherai dans aucune
   réponse, aucun rapport, aucun journal.

### Ce que je ferai, dans cet ordre, et ce que vous verrez

1. Écriture des deux valeurs dans `.env` (le fichier n'est jamais versionné), puis redémarrage.
2. `GET /api/telegram/status` → je vous montre le **mode** et l'état de la file, jamais le jeton :
   attendu `DRY_RUN` (les deux variables présentes), file vide.
3. `python3 backend/tools/telegram_setup.py --send-test` → **message réel** de vérification
   (« test de configuration »). Si le jeton ou le chat est mauvais, l'erreur exacte de Telegram
   est affichée, nettoyée de tout jeton.
4. Passage en `TELEGRAM_MODE=REAL`, redémarrage, puis `POST /api/telegram/test` : cette route
   passe par la **file durable** exactement comme une vraie alerte — message au format
   `🚨 SMART MARKET VISION` + la **capture PNG réelle** de la Phase 7 si une capture existe.
5. `GET /api/telegram/history` : l'alerte avec son `message_id` Telegram, ses `attempts`, son
   `capture_id` — la preuve que la chaîne complète fonctionne.

### Ensuite, à vous de décider

- Je remets `TELEGRAM_MODE=DRY_RUN` (aucun envoi automatique) **sauf** si vous voulez que les
  alertes partent en réel : dites-le explicitement.
- Je peux aussi **retirer le jeton du `.env`** après le test, si vous préférez qu'il ne reste
  pas dans cet espace.

---

## 3. Rappels qui ne changent pas

- Le projet **n'exécute aucun ordre** : le message de test est informatif, aucun broker n'est
  contacté, aucune position n'est ouverte.
- Un bot Telegram ne peut pas écrire le premier : **ouvrez la conversation avec votre bot et
  envoyez `/start`** avant le test, sinon Telegram répond `chat not found`.
- Aucune valeur secrète n'a été, ni ne sera, écrite dans le dépôt Git, dans un rapport ou dans
  un journal : `.gitignore` exclut `.env` et `.env.*`, et `PUSH_VERS_GITHUB.sh` refuse de
  pousser si un `.env` est suivi ou si un motif de jeton apparaît dans un fichier suivi.
