"""Assistant de configuration Telegram — SANS jamais afficher le jeton.

Trois usages, du plus sûr au plus engageant :

    python3 tools/telegram_setup.py                 # état de la configuration
    python3 tools/telegram_setup.py --list-chats    # trouve votre chat_id
    python3 tools/telegram_setup.py --send-test     # envoi RÉEL d'un message de test

Règles respectées (elles sont la raison d'être de ce script) :
  * le jeton n'est JAMAIS affiché, ni tronqué à l'écran, ni recopié dans un
    fichier : il n'est lu que depuis `.env`, et tout texte d'erreur est nettoyé
    avant affichage (l'URL de l'API Telegram contient le jeton) ;
  * le script n'écrit rien dans `.env` : c'est vous qui collez les valeurs ;
  * `--send-test` n'est exécuté que si vous le demandez explicitement, et il
    prévient qu'il fait un VRAI appel réseau (le mode DRY_RUN de l'application
    ne s'applique pas à cette vérification directe du jeton).

Ce script ne passe aucun ordre, ne touche à aucune position : le projet est un
scanner/observateur.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]  # backend/
sys.path.insert(0, str(BASE_DIR))

API_BASE = "https://api.telegram.org"

STEPS = """
Pour activer Telegram (3 minutes) :

  1. Dans Telegram, ouvrez une conversation avec @BotFather.
     - envoyez /newbot, choisissez un nom puis un identifiant terminant par "bot"
     - BotFather renvoie un JETON (suite de chiffres, deux-points, lettres)
     - ne le partagez avec personne et ne le collez pas dans un chat

  2. Ouvrez la conversation avec VOTRE nouveau bot et envoyez-lui /start.
     (un bot ne peut pas écrire en premier : sans ce message, il n'y a pas de chat)

  3. Renseignez le fichier .env à la racine du projet :
         TELEGRAM_BOT_TOKEN=le-jeton-fourni-par-BotFather
         TELEGRAM_CHAT_ID=            <- laissez vide pour l'instant

  4. Relancez ce script avec --list-chats : il affiche vos conversations et
     l'identifiant à recopier dans TELEGRAM_CHAT_ID.

  5. Vérifiez la configuration :
         python3 tools/telegram_setup.py --send-test      (message réel)
     puis, dans l'application, POST /api/telegram/test : cette route passe par
     la file durable (outbox) exactement comme une vraie alerte.

  Rappel des modes : deux variables présentes NE SUFFISENT PAS à envoyer des
  alertes réelles. Tant que TELEGRAM_MODE=DRY_RUN, l'outbox compose le message
  et le marque SENT sans aucun appel réseau. Le passage en REAL se fait
  uniquement en mettant TELEGRAM_MODE=REAL dans .env, puis en redémarrant.

  Vérification dans l'application : GET /api/telegram/status affiche le mode
  (NOT_CONFIGURED / DRY_RUN / REAL), la file et l'état du dispatcher.
"""


def mask(value: str | None, keep: int = 6) -> str:
    """Même masquage que l'application : jamais la valeur, seulement sa présence."""
    if not value:
        return "NOT_SET"
    if len(value) <= keep:
        return "*" * len(value)
    return f"{value[:keep]}{'*' * 6}"


def scrub(text: str, token: str | None) -> str:
    """Retire le jeton d'un texte avant de l'afficher (les URL en contiennent)."""
    if token:
        text = text.replace(token, mask(token))
    return text


async def call(token: str, method: str, payload: dict | None = None) -> tuple[bool, object]:
    """Un appel à l'API Bot. L'URL (qui contient le jeton) n'est jamais affichée."""
    import httpx

    url = f"{API_BASE}/bot{token}/{method}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, data=payload or {})
    except Exception as exc:  # réseau, DNS, proxy...
        return False, scrub(f"{type(exc).__name__} : {exc}", token)
    if response.status_code >= 400:
        try:
            body = response.json()
            return False, scrub(str(body.get("description") or f"HTTP {response.status_code}"), token)
        except Exception:
            return False, f"HTTP {response.status_code}"
    try:
        body = response.json()
    except Exception:
        return False, "réponse illisible de l'API Telegram"
    if not body.get("ok"):
        return False, scrub(str(body.get("description", "erreur inconnue")), token)
    return True, body.get("result")


def describe_chats(updates: list[dict]) -> list[tuple[str, str]]:
    """Extrait (id, description) des conversations vues par le bot."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for update in updates or []:
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            entity = update.get(key)
            if not isinstance(entity, dict):
                continue
            chat = entity.get("chat") or {}
            chat_id = chat.get("id")
            if chat_id is None:
                continue
            identifier = str(chat_id)
            if identifier in seen:
                continue
            seen.add(identifier)
            label = chat.get("title") or chat.get("username") or chat.get("first_name") or "sans nom"
            found.append((identifier, f"{label} (type {chat.get('type', 'inconnu')})"))
    return found


async def main() -> int:
    parser = argparse.ArgumentParser(description="Configuration Telegram (sans afficher le jeton)")
    parser.add_argument("--list-chats", action="store_true",
                        help="interroge l'API pour trouver votre TELEGRAM_CHAT_ID")
    parser.add_argument("--send-test", action="store_true",
                        help="envoie un VRAI message de test (appel réseau réel)")
    args = parser.parse_args()

    try:
        from app.config import settings
    except ModuleNotFoundError as exc:  # dépendances non installées
        print(f"Dépendance manquante : {exc.name}")
        print("Installez d'abord le runtime backend :")
        print(f"  cd {BASE_DIR} && python3 -m pip install -r requirements.txt")
        return 1

    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    app_mode = settings.telegram_mode if hasattr(settings, "telegram_mode") else None

    print("=== ÉTAT DE LA CONFIGURATION TELEGRAM ===")
    print(f"jeton présent      : {bool(token)} ({mask(token)})")
    print(f"chat_id présent    : {bool(chat_id)} ({mask(chat_id, keep=2)})")
    print(f"notifications      : {'activées' if settings.telegram_enabled else 'désactivées'} (TELEGRAM_ENABLED)")
    print(f"mode demandé (.env): {app_mode or 'DRY_RUN (défaut)'}")
    resolved = "REAL" if (token and chat_id and str(app_mode).upper() == "REAL") else (
        "DRY_RUN" if (token and chat_id) else "NOT_CONFIGURED")
    print(f"mode effectif      : {resolved}")
    print("(règle : REAL seulement si les DEUX variables existent ET TELEGRAM_MODE=REAL)")

    if not token:
        print(STEPS)
        return 2 if (args.list_chats or args.send_test) else 0

    # ------------------------------------------------------------- vérification
    ok, result = await call(token, "getMe")
    if not ok:
        print(f"\n❌ Le jeton est refusé ou le réseau est indisponible : {result}")
        print("   Vérifiez le jeton auprès de @BotFather (il a pu être révoqué).")
        return 1
    assert isinstance(result, dict)
    print(f"\n✅ Bot joignable : @{result.get('username', '?')} "
          f"({result.get('first_name', 'sans nom')})")

    if args.list_chats or not chat_id:
        ok, updates = await call(token, "getUpdates")
        if not ok:
            print(f"❌ Impossible de lire les conversations : {updates}")
            return 1
        chats = describe_chats(updates if isinstance(updates, list) else [])
        if not chats:
            print("\nAucune conversation trouvée.")
            print("  1) ouvrez la conversation avec votre bot et envoyez-lui /start")
            print("  2) relancez : python3 tools/telegram_setup.py --list-chats")
            print("  (si vous visez un canal ou un groupe : ajoutez-y le bot, puis renvoyez /start)")
            return 0
        print("\nConversations trouvées (recopiez l'identifiant dans TELEGRAM_CHAT_ID) :")
        for identifier, label in chats:
            print(f"  {identifier:>16}  {label}")
        if not chat_id:
            print("\nEnsuite : TELEGRAM_CHAT_ID=<identifiant> dans .env, puis relancez ce script.")
        return 0

    # ------------------------------------------------------------ envoi de test
    if args.send_test:
        print("\n⚠️  --send-test fait un VRAI appel réseau : un message va être déposé dans "
              "votre conversation Telegram.")
        print("    (le mode DRY_RUN de l'application ne s'applique pas à cette vérification "
              "directe du jeton)")
        ok, result = await call(token, "sendMessage", {
            "chat_id": chat_id,
            "text": "✅ SMART MARKET VISION — test de configuration.\n"
                    "Aucune exécution d'ordre : ce projet observe et alerte uniquement.",
            "disable_web_page_preview": True,
        })
        if not ok:
            print(f"❌ Envoi refusé : {result}")
            print("   Causes fréquentes : chat_id erroné, bot jamais démarré dans cette "
                  "conversation, bot retiré du groupe/canal.")
            return 1
        message_id = (result or {}).get("message_id") if isinstance(result, dict) else None
        print(f"✅ Message reçu par Telegram (message_id={message_id}).")

    print("\nÉtat : la configuration est complète."
          f"\n  - mode DRY_RUN : les alertes sont composées et marquées SENT sans réseau."
          f"\n  - passage en envoi réel : TELEGRAM_MODE=REAL dans .env, puis redémarrage."
          f"\n  - vérification dans l'application : GET /api/telegram/status")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
